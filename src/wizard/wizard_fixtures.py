"""Test fixtures for the wizard — imported explicitly by its *_test.py
files (no conftest)."""

import os
import shutil
import subprocess  # nosec B404 — ssh-keygen in tests, no shell
from pathlib import Path

from src.wizard.wizard_record import CommandOutput, Deployment, SshAccount
from src.wizard.wizard_service import WizardService

SSH_KEYGEN = shutil.which("ssh-keygen")


def ssh_keygen(*args: str) -> str:
    """Run the real ssh-keygen; return stdout."""
    assert SSH_KEYGEN is not None, "ssh-keygen not found on PATH"
    return (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [SSH_KEYGEN, *args], check=True, capture_output=True, text=True
        ).stdout
    )


def ec2_style_pem(tmp_path: Path) -> tuple[str, str]:
    """An RSA key in PEM format, like an EC2 .pem: (private PEM, public line).
    The private key is written to ``tmp_path / "my-key.pem"``."""
    key_path = tmp_path / "my-key.pem"
    ssh_keygen(
        "-q", "-t", "rsa", "-b", "2048", "-m", "PEM", "-N", "", "-f", str(key_path)
    )
    return key_path.read_text(), ssh_keygen("-y", "-f", str(key_path)).strip()


class FakeProbe:
    """Stands in for systemctl / ssh-keyscan / sshd -T, which need root and
    a real sshd. Healthy by default; a test breaks one by name."""

    def __init__(self) -> None:
        self.outputs: dict[str, CommandOutput] = {
            "systemctl": CommandOutput(returncode=0, stdout="active\n"),
            "ssh-keyscan": CommandOutput(
                returncode=0, stdout="localhost ssh-ed25519 AAAAhostkey\n"
            ),
            "sshd": CommandOutput(
                returncode=0, stdout="port 22\npubkeyauthentication yes\n"
            ),
        }

    def __call__(self, args: list[str]) -> CommandOutput:
        """The canned output for this command (by binary name)."""
        return self.outputs[Path(args[0]).name]


def account(tmp_path: Path) -> SshAccount:
    """The installer account, homed under tmp_path, owned by this test user."""
    home = tmp_path / "home" / "joe"
    home.mkdir(parents=True, exist_ok=True)
    return SshAccount(name="joe", home=home, uid=os.getuid(), gid=os.getgid())


def make_service(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    probe: FakeProbe | None = None,
) -> WizardService:
    """A WizardService on tmp_path with a healthy (or given) fake probe."""
    return WizardService(
        account=account(tmp_path),
        deployment=deployment,
        applied_marker_path=tmp_path / "applied",
        run_probe=probe or FakeProbe(),
    )
