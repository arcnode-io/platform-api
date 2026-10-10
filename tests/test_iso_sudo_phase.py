"""Integration test for phases/sudo.sh — the installer's account gets sudo
even when a root password was set (Debian then skips sudo for it).

Runs the real phase in a plain Debian container with a UID 1000 account
and no sudo package, like an attended install that set a root password.
"""

from pathlib import Path

from testcontainers.core.container import DockerContainer

REPO_ROOT = Path(__file__).parent.parent
SUDO_PHASE = REPO_ROOT / "src" / "iso" / "phases" / "sudo.sh"


def test_the_installer_account_can_sudo() -> None:
    # Arrange
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_volume_mapping(str(SUDO_PHASE), "/root/sudo.sh", "ro")
    )
    with container:
        container.exec(["useradd", "-m", "-u", "1000", "customer"])
        # setup.sh's step 1 has already run apt-get update by this point.
        container.exec(["apt-get", "update", "-qq"])

        # Act
        exit_code, output = container.exec(["sh", "/root/sudo.sh"])

        # Assert
        actual = container.exec(["id", "-nG", "customer"]).output.decode().split()
        assert exit_code == 0, output.decode()
        assert "sudo" in actual
        assert container.exec(["test", "-x", "/usr/bin/sudo"]).exit_code == 0
