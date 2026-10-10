"""Integration test for test-mode.sh — the one command that lowers the
hardware check's minimums for a friend's under-spec test box.

Runs the real script (src/iso/phases/test-mode.sh, never a copy) in a plain
Debian container against the real wizard-cfg.yml setup.sh writes. systemctl
is faked: there's no systemd in the container, and restarting the wizard is
systemd's job, not this script's logic.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer

REPO_ROOT = Path(__file__).parent.parent
TEST_MODE_SCRIPT = REPO_ROOT / "src" / "iso" / "phases" / "test-mode.sh"
TEST_ORDER = REPO_ROOT / "src" / "iso" / "phases" / "test-order"
SETUP_TEXT = (REPO_ROOT / "src" / "iso" / "setup.sh").read_text()
FAKE_SYSTEMCTL = '#!/bin/sh\necho "$@" >> /root/systemctl.log\n'


def _production_cfg() -> str:
    """wizard-cfg.yml exactly as setup.sh writes it."""
    marker = "cat > /etc/arcnode/wizard-cfg.yml <<'EOF'\n"
    start = SETUP_TEXT.index(marker) + len(marker)
    return SETUP_TEXT[start : SETUP_TEXT.index("\nEOF", start)]


@pytest.fixture(scope="module")
def box() -> Iterator[DockerContainer]:
    """A Debian box from the generic base ISO (no order): the script and the
    test order where setup.sh installs them, the production wizard-cfg.yml,
    and an ordinary login account."""
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_volume_mapping(str(TEST_MODE_SCRIPT), "/src/test-mode.sh", "ro")
        .with_volume_mapping(
            str(TEST_ORDER), "/usr/local/share/arcnode/test-order", "ro"
        )
    )
    with container:
        container.exec(
            [
                "install",
                "-m",
                "0755",
                "/src/test-mode.sh",
                "/usr/local/sbin/test-mode.sh",
            ]
        )
        container.exec(["useradd", "-m", "friend"])
        container.exec(["mkdir", "-p", "/etc/arcnode"])
        for path, text in [
            ("/etc/arcnode/wizard-cfg.yml", _production_cfg()),
            ("/usr/local/bin/systemctl", FAKE_SYSTEMCTL),
        ]:
            container.exec(["sh", "-c", f"cat > {path} <<'TEST_EOF'\n{text}\nTEST_EOF"])
        container.exec(["chmod", "+x", "/usr/local/bin/systemctl"])
        yield container


def test_without_root_refuses_and_says_how(box: DockerContainer) -> None:
    # Arrange — an ordinary login account

    # Act
    exit_code, output = box.exec(
        ["runuser", "-u", "friend", "--", "/usr/local/sbin/test-mode.sh"]
    )

    # Assert
    assert exit_code != 0
    assert "sudo test-mode.sh" in output.decode()


def test_as_root_lowers_the_minimums_and_restarts_the_wizard(
    box: DockerContainer,
) -> None:
    # Arrange
    expected = (
        "deployment: on-prem\n"
        "hardware:\n"
        "  vcpus: 4\n"
        "  memory_gib: 16\n"
        "  gpus: 0\n"
        "  gpu_memory_gb: 0\n"
        "  disk_gb: 100\n"
        "  disk_nvme: false\n"
        "ollama:\n"
        "  chat_model: qwen3:0.6b\n"
        "  embedding_model: qwen3-embedding:0.6b\n"
        "  context_length: 8192\n"
    )

    # Act
    exit_code, output = box.exec(["test-mode.sh"])

    # Assert
    actual = box.exec(["cat", "/etc/arcnode/wizard-cfg.yml"]).output.decode()
    restarts = box.exec(["cat", "/root/systemctl.log"]).output.decode()
    assert exit_code == 0, output
    assert actual == expected
    assert restarts == "restart arcnode-wizard\n"


def test_gives_a_box_with_no_order_the_test_sites(box: DockerContainer) -> None:
    # Arrange — the previous test ran test-mode.sh on an order-less box
    expected = (TEST_ORDER / "site.yml").read_text()

    # Act
    actual = box.exec(["cat", "/etc/arcnode/order/site.yml"]).output.decode()

    # Assert
    assert actual == expected


def test_keeps_a_real_order(box: DockerContainer) -> None:
    # Arrange — a box installed from a per-order ISO
    box.exec(["sh", "-c", "echo 'site_id: real_site' > /etc/arcnode/order/site.yml"])

    # Act
    exit_code, output = box.exec(["test-mode.sh"])

    # Assert
    actual = box.exec(["cat", "/etc/arcnode/order/site.yml"]).output.decode()
    assert exit_code == 0, output
    assert actual == "site_id: real_site\n"
