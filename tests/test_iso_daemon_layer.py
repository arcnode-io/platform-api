"""Integration tests for the daemon layer (Docker + Postgres install, role/db
bootstrap, verification, docker_runtime hand-off) — on a real local
QEMU/KVM VM, not mocked.

Pins the bug found via manual Vagrant verification: gating docker_runtime
on the daemon layer via Requires=/After= alone left it silently never
starting — the one-shot .path trigger had already fired (and aborted)
before the daemon layer finished, and Requires=/After= doesn't
retroactively start anything. The daemon layer's Wants=/Before= on
docker_runtime is what the ordering assertion actually checks.

`uv run pytest -m vagrant tests/test_iso_daemon_layer.py`
"""

import re

import pytest

from tests.fixtures.vagrant import (
    deploy_daemon_layer_fresh,
    extract_heredoc,
    reboot,
    ssh,
    vm,  # noqa: F401 — pytest fixture, used by name
    wait_for_unit,
)

pytestmark = pytest.mark.vagrant

DAEMON_LAYER_LOG = "/var/log/arcnode-daemon-layer.log"


def test_daemon_layer_install_then_docker_runtime_handoff(vm: None) -> None:
    """Touching the wizard's apply-marker installs + verifies Docker and
    Postgres, then hands off to docker_runtime — in order, automatically."""
    # Arrange
    assert "Wants=arcnode-docker-runtime.service" in extract_heredoc(
        "/etc/systemd/system/arcnode-daemon-layer.service"
    ), "the actual fix — if this regresses, docker_runtime silently never starts"
    deploy_daemon_layer_fresh()

    # Act: the one action that simulates the wizard's apply()
    result = ssh("sudo touch /etc/arcnode/.wizard-applied")
    assert result.returncode == 0, result.stderr

    # Assert: daemon layer completes, and says it verified both daemons
    actual_state = wait_for_unit("arcnode-daemon-layer.service")
    log = ssh(f"sudo cat {DAEMON_LAYER_LOG}").stdout
    assert actual_state == "active", log
    assert "verify docker: ok" in log
    assert "verify postgres: ok" in log

    actual_secrets = ssh("sudo cat /etc/arcnode/secrets.env").stdout
    document_url_match = re.search(r"DOCUMENT_URL=(\S+)", actual_secrets)
    assert document_url_match is not None, actual_secrets
    result = ssh(f'psql "{document_url_match.group(1)}" -tAc "select current_user"')
    assert (
        result.stdout.strip() == "device_api"
    ), "the generated credential must actually authenticate"

    # Assert: docker_runtime started off the daemon layer's own completion
    actual_runtime_state = wait_for_unit("arcnode-docker-runtime.service", attempts=24)
    assert (
        actual_runtime_state == "active"
    ), "docker_runtime never started — the Wants=/Before= handoff regressed"
    daemon_layer_started = ssh(
        "systemctl show arcnode-daemon-layer.service -p ActiveEnterTimestampMonotonic --value"
    ).stdout.strip()
    docker_runtime_started = ssh(
        "systemctl show arcnode-docker-runtime.service -p ActiveEnterTimestampMonotonic --value"
    ).stdout.strip()
    assert int(docker_runtime_started) >= int(daemon_layer_started)

    result = ssh(
        "sudo docker compose -f /opt/arcnode/docker-compose.yaml ps --format '{{.State}}'"
    )
    assert result.stdout.strip() == "running", result.stdout


def test_daemon_layer_fails_when_document_url_does_not_authenticate(vm: None) -> None:
    """secrets.env and the real postgres role drifting apart must fail the
    unit loudly — not log "installed" and hand off to a stack that can't
    connect."""
    # Arrange: a fully successful run, then corrupt the stored credential
    deploy_daemon_layer_fresh()
    ssh("sudo touch /etc/arcnode/.wizard-applied")
    assert wait_for_unit("arcnode-daemon-layer.service") == "active"
    ssh(
        "sudo systemctl stop arcnode-daemon-layer.service && "
        "sudo sed -i 's|device_api:[0-9a-f]*@|device_api:wrongpassword@|' /etc/arcnode/secrets.env"
    )

    # Act
    ssh("sudo systemctl start arcnode-daemon-layer.service")

    # Assert
    actual_state = wait_for_unit("arcnode-daemon-layer.service", attempts=12)
    log = ssh(f"sudo cat {DAEMON_LAYER_LOG}").stdout
    assert actual_state == "failed", log
    assert "verify postgres: FAILED" in log


def test_both_layers_rerun_once_on_boot_after_apply(vm: None) -> None:
    """After a successful apply, a reboot runs both layers again (once) —
    the edge-triggered .path units don't fire at boot, so this pins that
    WantedBy= + ConditionPathExists= actually covers it."""
    # Arrange
    deploy_daemon_layer_fresh()
    ssh("sudo touch /etc/arcnode/.wizard-applied")
    assert wait_for_unit("arcnode-daemon-layer.service") == "active"
    assert wait_for_unit("arcnode-docker-runtime.service", attempts=24) == "active"

    # Act
    reboot()

    # Assert
    actual_daemon_layer = wait_for_unit("arcnode-daemon-layer.service")
    actual_docker_runtime = wait_for_unit("arcnode-docker-runtime.service", attempts=24)
    boot_log = ssh(
        "sudo journalctl -b -u arcnode-daemon-layer.service --no-pager"
    ).stdout
    assert actual_daemon_layer == "active", boot_log
    assert actual_docker_runtime == "active"
    result = ssh(
        "sudo docker compose -f /opt/arcnode/docker-compose.yaml ps --format '{{.State}}'"
    )
    assert result.stdout.strip() == "running", result.stdout
