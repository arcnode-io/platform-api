"""Integration test for the daemon-layer provisioning (Docker + Postgres
install, Postgres role/db bootstrap, docker_runtime hand-off) — against a
real local QEMU/KVM VM, not mocked.

Parses the exact heredoc blocks out of the real src/iso/setup.sh rather
than duplicating them here, so this test can never silently drift from
what actually ships.

Pins the bug found via manual Vagrant verification: an earlier version
gated docker_runtime on the daemon layer via Requires=/After= alone, and
it silently never started — the one-shot .path trigger had already fired
(and aborted) once before the daemon layer finished, and Requires=/After=
only blocks an early start, it doesn't retroactively start something once
a dependency becomes ready later. The fix (the daemon layer unit
declaring Wants=/Before= on docker_runtime) is what the ordering
assertion below actually checks, not just "both ended up active
eventually."

Requires `vagrant` + the `vagrant-qemu` plugin + /dev/kvm access —
`uv run pytest -m vagrant tests/test_iso_daemon_layer.py`.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.vagrant

REPO_ROOT = Path(__file__).parent.parent
VAGRANT_DIR = REPO_ROOT / "src" / "iso" / "vagrant"
SETUP_SH_TEXT = (REPO_ROOT / "src" / "iso" / "setup.sh").read_text()
VAGRANT_BIN = shutil.which("vagrant")


def _extract_heredoc(write_target: str) -> str:
    """Pull one `cat > <write_target> <<'EOF' ... EOF` block's body out of
    the real setup.sh — the single source of truth this test checks
    against, never a copy that could silently drift from what ships."""
    marker = f"cat > {write_target} <<'EOF'\n"
    start = SETUP_SH_TEXT.index(marker) + len(marker)
    end = SETUP_SH_TEXT.index("\nEOF", start)
    return SETUP_SH_TEXT[start:end]


def _ssh(command: str, timeout: int = 240) -> subprocess.CompletedProcess:
    assert VAGRANT_BIN is not None, "vagrant not found on PATH"
    return subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args, test-local command string
        [VAGRANT_BIN, "ssh", "-c", command],
        cwd=VAGRANT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_remote_file(remote_path: str, content: str, executable: bool = False) -> None:
    """Writes `content` to `remote_path` on the VM via a quoted heredoc
    over SSH — no local-temp-file/upload round trip needed."""
    # `&&` can't start its own line right after a heredoc terminator (no
    # preceding command on that line for it to join) — a plain newline,
    # a separate statement, works fine instead.
    mode_cmd = f"sudo chmod +x {remote_path}\n" if executable else ""
    heredoc = (
        f"sudo tee {remote_path} > /dev/null <<'REMOTE_EOF'\n"
        f"{content}\nREMOTE_EOF\n{mode_cmd}"
    )
    result = _ssh(heredoc)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def vm() -> Iterator[None]:
    """Boots the shared test VM if it isn't already running. `vagrant up`
    on an already-running VM is a documented no-op, so this is safe to
    call every test session regardless of prior state."""
    assert VAGRANT_BIN is not None, "vagrant not found on PATH"
    result = subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
        [VAGRANT_BIN, "up", "--provider", "qemu"],
        cwd=VAGRANT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    yield


def test_daemon_layer_install_then_docker_runtime_handoff(vm: None) -> None:
    """Touching the wizard's apply-marker installs Docker + Postgres,
    bootstraps the device_api role/db, and hands off to the
    docker_runtime compose layer — in that order, automatically, with no
    second trigger needed."""
    # Arrange: deploy the real units (parsed from setup.sh) onto a
    # genuinely clean slate — both path units stopped (so nothing can
    # fire mid-setup), both services stopped (RemainAfterExit=yes keeps a
    # prior success looking "active" otherwise), marker/log/secrets gone.
    daemon_layer_script = _extract_heredoc("/usr/local/sbin/arcnode-daemon-layer.sh")
    daemon_layer_unit = _extract_heredoc("/etc/systemd/system/arcnode-daemon-layer.service")
    daemon_layer_path = _extract_heredoc("/etc/systemd/system/arcnode-daemon-layer.path")
    docker_runtime_unit = _extract_heredoc("/etc/systemd/system/arcnode-docker-runtime.service")

    assert "Wants=arcnode-docker-runtime.service" in daemon_layer_unit, (
        "the actual fix — if this regresses, docker_runtime silently never starts"
    )
    assert "arcnode-daemon-layer.service" in docker_runtime_unit

    _ssh(
        "sudo systemctl stop arcnode-daemon-layer.path arcnode-docker-runtime.path "
        "arcnode-daemon-layer.service arcnode-docker-runtime.service 2>/dev/null; "
        "sudo systemctl reset-failed 2>/dev/null; "
        "sudo mkdir -p /etc/arcnode /opt/arcnode; "
        "sudo rm -f /etc/arcnode/.wizard-applied /etc/arcnode/secrets.env "
        "/var/log/arcnode-daemon-layer.log; "
        # Drop the role/db too, not just secrets.env — otherwise a
        # re-run here (unlike a genuinely fresh appliance) hits the
        # bootstrap script's own idempotent "already exists" branch,
        # which correctly skips writing DOCUMENT_URL again, making this
        # test's reset itself the thing that's not actually clean.
        "if command -v psql > /dev/null 2>&1; then "
        "  sudo runuser -u postgres -- dropdb --if-exists document 2>/dev/null; "
        "  sudo runuser -u postgres -- psql -c "
        "'DROP ROLE IF EXISTS device_api' 2>/dev/null; "
        "fi"
    )
    _write_remote_file(
        "/usr/local/sbin/arcnode-daemon-layer.sh", daemon_layer_script, executable=True
    )
    _write_remote_file("/etc/systemd/system/arcnode-daemon-layer.service", daemon_layer_unit)
    _write_remote_file("/etc/systemd/system/arcnode-daemon-layer.path", daemon_layer_path)
    _write_remote_file("/etc/systemd/system/arcnode-docker-runtime.service", docker_runtime_unit)
    _write_remote_file(
        "/etc/systemd/system/arcnode-docker-runtime.path",
        _extract_heredoc("/etc/systemd/system/arcnode-docker-runtime.path"),
    )
    _write_remote_file(
        "/opt/arcnode/docker-compose.yaml",
        "services:\n  test-service:\n    image: alpine:latest\n    command: sleep infinity\n",
    )
    # Docker's apt repo is normally configured by setup.sh's phase 1
    # (chroot-time, independent of the wizard) — reproduced here since
    # this test targets a generic cloud box, not the real preseeded ISO.
    _ssh(
        "sudo install -m 0755 -d /etc/apt/keyrings && "
        "sudo curl -fsSL https://download.docker.com/linux/debian/gpg "
        "-o /etc/apt/keyrings/docker.asc && "
        "sudo chmod a+r /etc/apt/keyrings/docker.asc && "
        'echo "deb [arch=$(dpkg --print-architecture) '
        "signed-by=/etc/apt/keyrings/docker.asc] "
        "https://download.docker.com/linux/debian "
        '$(. /etc/os-release && echo $VERSION_CODENAME) stable" | '
        "sudo tee /etc/apt/sources.list.d/docker.list > /dev/null"
    )
    result = _ssh(
        "sudo systemctl daemon-reload && "
        "sudo systemctl start arcnode-daemon-layer.path arcnode-docker-runtime.path"
    )
    assert result.returncode == 0, result.stderr

    # Act: the one action that simulates the wizard's apply() — nothing
    # else is triggered manually from here.
    result = _ssh("sudo touch /etc/arcnode/.wizard-applied")
    assert result.returncode == 0, result.stderr

    # Assert: daemon layer actually completes (bounded wait — apt install
    # of two real daemons, not instant, but never silently infinite).
    result = _ssh(
        "for i in $(seq 1 60); do "
        '  state=$(sudo systemctl is-active arcnode-daemon-layer.service); '
        '  [ "$state" = "active" ] && break; '
        '  [ "$state" = "failed" ] && { sudo cat /var/log/arcnode-daemon-layer.log; exit 1; }; '
        "  sleep 5; "
        "done; "
        "sudo systemctl is-active arcnode-daemon-layer.service",
        timeout=360,
    )
    actual_daemon_layer_state = result.stdout.strip()
    assert actual_daemon_layer_state == "active", result.stdout + result.stderr

    result = _ssh("sudo systemctl is-active docker postgresql")
    actual_daemon_states = result.stdout.strip().splitlines()
    assert actual_daemon_states == ["active", "active"], result.stdout

    result = _ssh("sudo cat /etc/arcnode/secrets.env")
    actual_secrets = result.stdout
    assert "DOCUMENT_URL=postgres://device_api:" in actual_secrets

    document_url_match = re.search(r"DOCUMENT_URL=(\S+)", actual_secrets)
    assert document_url_match is not None
    result = _ssh(f'psql "{document_url_match.group(1)}" -c "select current_user"')
    assert "device_api" in result.stdout, "the generated credential must actually authenticate"

    # Assert: docker_runtime started automatically off the daemon layer's
    # own completion — the actual regression this test exists to pin.
    # Requires=/After= alone (confirmed via manual testing) lets
    # docker_runtime's .path trigger fire-and-abort before the daemon
    # layer finishes, with nothing to retrigger it afterward; only the
    # daemon layer's Wants=/Before= on docker_runtime makes this work.
    result = _ssh(
        "for i in $(seq 1 24); do "
        '  state=$(sudo systemctl is-active arcnode-docker-runtime.service); '
        '  [ "$state" = "active" ] && break; '
        "  sleep 5; "
        "done; "
        "sudo systemctl is-active arcnode-docker-runtime.service",
        timeout=150,
    )
    actual_docker_runtime_state = result.stdout.strip()
    assert actual_docker_runtime_state == "active", (
        "docker_runtime never started — the Wants=/Before= handoff regressed"
    )

    daemon_layer_started = _ssh(
        "systemctl show arcnode-daemon-layer.service -p ActiveEnterTimestamp "
        "--value"
    ).stdout.strip()
    docker_runtime_started = _ssh(
        "systemctl show arcnode-docker-runtime.service -p ActiveEnterTimestamp "
        "--value"
    ).stdout.strip()
    assert docker_runtime_started >= daemon_layer_started, (
        "docker_runtime must never start before the daemon layer it depends on"
    )

    result = _ssh("sudo docker compose -f /opt/arcnode/docker-compose.yaml ps --format '{{.State}}'")
    assert result.stdout.strip() == "running", result.stdout
