"""Vagrant/QEMU VM fixtures for ISO provisioning integration tests.

Units under test are parsed straight out of the real src/iso/setup.sh
heredocs — never copies — so a test can't silently drift from what ships.
Needs `vagrant` + the `vagrant-qemu` plugin + /dev/kvm access.
"""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).parent.parent.parent
VAGRANT_DIR: Final[Path] = REPO_ROOT / "src" / "iso" / "vagrant"
SETUP_SH_TEXT: Final[str] = (REPO_ROOT / "src" / "iso" / "setup.sh").read_text()
VAGRANT_BIN: Final[str | None] = shutil.which("vagrant")


def extract_heredoc(write_target: str) -> str:
    """Body of one `cat > <write_target> <<'EOF' ... EOF` block in setup.sh."""
    marker = f"cat > {write_target} <<'EOF'\n"
    start = SETUP_SH_TEXT.index(marker) + len(marker)
    end = SETUP_SH_TEXT.index("\nEOF", start)
    return SETUP_SH_TEXT[start:end]


def ssh(command: str, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    """Run a shell command on the VM via `vagrant ssh -c`."""
    assert VAGRANT_BIN is not None, "vagrant not found on PATH"
    return subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args, test-local command string
        [VAGRANT_BIN, "ssh", "-c", command],
        cwd=VAGRANT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def write_remote_file(remote_path: str, content: str, executable: bool = False) -> None:
    """Write `content` to `remote_path` on the VM via a quoted heredoc."""
    # `&&` can't start its own line right after a heredoc terminator — a
    # plain newline (separate statement) works instead.
    mode_cmd = f"sudo chmod +x {remote_path}\n" if executable else ""
    heredoc = (
        f"sudo tee {remote_path} > /dev/null <<'REMOTE_EOF'\n"
        f"{content}\nREMOTE_EOF\n{mode_cmd}"
    )
    result = ssh(heredoc)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def vm() -> Iterator[None]:
    """Boot the shared test VM if needed — `vagrant up` on a running VM is a no-op."""
    assert VAGRANT_BIN is not None, "vagrant not found on PATH"
    result = (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [VAGRANT_BIN, "up", "--provider", "qemu"],
            cwd=VAGRANT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    yield


def reboot() -> None:
    """Real reboot of the VM (`vagrant reload`), blocking until SSH is back."""
    assert VAGRANT_BIN is not None, "vagrant not found on PATH"
    result = (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [VAGRANT_BIN, "reload"],
            cwd=VAGRANT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr


def deploy_daemon_layer_fresh() -> None:
    """Reset the VM to a pre-wizard-apply state and deploy the real units.

    Stops both path units (nothing fires mid-setup) and both services
    (RemainAfterExit=yes keeps a prior success "active" otherwise), drops
    the postgres role/db too — otherwise the bootstrap's idempotent
    "already exists" branch skips writing DOCUMENT_URL, so the reset
    itself wouldn't actually be clean.
    """
    ssh(
        "sudo systemctl stop arcnode-daemon-layer.path arcnode-docker-runtime.path "
        "arcnode-daemon-layer.service arcnode-docker-runtime.service 2>/dev/null; "
        "sudo systemctl reset-failed 2>/dev/null; "
        "sudo mkdir -p /etc/arcnode /opt/arcnode; "
        "sudo rm -f /etc/arcnode/.wizard-applied /etc/arcnode/secrets.env "
        "/var/log/arcnode-daemon-layer.log; "
        "if command -v psql > /dev/null 2>&1; then "
        "  sudo runuser -u postgres -- dropdb --if-exists document 2>/dev/null; "
        "  sudo runuser -u postgres -- psql -c "
        "'DROP ROLE IF EXISTS device_api' 2>/dev/null; "
        "fi"
    )
    write_remote_file(
        "/usr/local/sbin/arcnode-daemon-layer.sh",
        extract_heredoc("/usr/local/sbin/arcnode-daemon-layer.sh"),
        executable=True,
    )
    for unit in (
        "arcnode-daemon-layer.service",
        "arcnode-daemon-layer.path",
        "arcnode-docker-runtime.service",
        "arcnode-docker-runtime.path",
    ):
        write_remote_file(
            f"/etc/systemd/system/{unit}",
            extract_heredoc(f"/etc/systemd/system/{unit}"),
        )
    write_remote_file(
        "/opt/arcnode/docker-compose.yaml",
        "services:\n  test-service:\n    image: alpine:latest\n    command: sleep infinity\n",
    )
    # Docker's apt repo is normally set up by setup.sh phase 1 (chroot-time)
    # — reproduced here since the test box is a generic cloud image.
    ssh(
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
    result = ssh(
        "sudo systemctl daemon-reload && "
        "sudo systemctl enable arcnode-daemon-layer.service arcnode-docker-runtime.service "
        "arcnode-daemon-layer.path arcnode-docker-runtime.path && "
        "sudo systemctl start arcnode-daemon-layer.path arcnode-docker-runtime.path"
    )
    assert result.returncode == 0, result.stderr


def wait_for_unit(unit: str, attempts: int = 60) -> str:
    """Poll a unit until active or failed (5s apart); return its final state."""
    result = ssh(
        f"for i in $(seq 1 {attempts}); do "
        f"  state=$(sudo systemctl is-active {unit}); "
        '  [ "$state" = "active" ] && break; '
        '  [ "$state" = "failed" ] && break; '
        "  sleep 5; "
        "done; "
        f"sudo systemctl is-active {unit}",
        timeout=attempts * 5 + 60,
    )
    return result.stdout.strip()
