"""The on-prem SSH page: bring-your-own key, verified."""

import os
import shutil
import subprocess  # nosec B404 — ssh-keygen below, absolute path, no shell
from typing import Final

from src.wizard.ssh_verify import verify_ssh
from src.wizard.system_runner import Runner
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker
from src.wizard.wizard_record import (
    ApplyRequest,
    ApplyResult,
    Deployment,
    SshAccount,
)

PRIVATE_KEY_HINT: Final[str] = (
    "That's your private key — keep it on your machine. Paste its public "
    "half instead; get it with: ssh-keygen -y -f private-key.pem"
)


class InvalidSshKeyError(Exception):
    """The pasted text isn't a single OpenSSH public key."""


class SshStepNotAvailableError(Exception):
    """The SSH step doesn't exist in the cloud — EC2 already set up SSH."""


class SshService:
    """The on-prem SSH step: authorizes the customer's own public key,
    verifies SSH, and only then disables the wizard. Doesn't exist in the
    cloud, where the EC2 launch key pair already works.

    ``run`` runs the system checks (systemctl, ssh-keyscan, sshd -T) —
    injected because they need root and a real sshd.
    """

    def __init__(
        self,
        *,
        account: SshAccount,
        deployment: Deployment,
        tracker: StepTracker,
        run: Runner,
    ) -> None:
        self._account = account
        self._deployment = deployment
        self._tracker = tracker
        self._run = run

    def apply(self, request: ApplyRequest) -> ApplyResult:
        """Validate + authorize the pasted public key, then verify — the
        gate: only when every check passes is the wizard marked applied. A
        failed check leaves it open so the person can fix sshd and retry
        (re-applying is safe)."""
        if self._deployment == Deployment.CLOUD:
            raise SshStepNotAvailableError("no SSH step in the cloud — EC2 set it up")
        if self._tracker.is_done("ssh"):
            raise StepAlreadyDoneError("SSH is already set up")
        key = request.ssh_public_key.strip()
        _validate_public_key(key)
        self._append_authorized_key(key)
        checks = verify_ssh(self._account, self._run, key)
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("ssh")
        return ApplyResult(verified=verified, account=self._account.name, checks=checks)

    def _append_authorized_key(self, key: str) -> None:
        # Reason: sshd's StrictModes silently ignores authorized_keys when
        # ~/.ssh or the file is writable by anyone but the owner — the key
        # would "install" fine and login would still fail.
        ssh_dir = self._account.home / ".ssh"
        authorized_keys = ssh_dir / "authorized_keys"
        ssh_dir.mkdir(exist_ok=True)
        already = (
            authorized_keys.is_file()
            and key in authorized_keys.read_text().splitlines()
        )
        if not already:
            with authorized_keys.open("a") as f:
                f.write(key + "\n")
        for path, mode in ((ssh_dir, 0o700), (authorized_keys, 0o600)):
            path.chmod(mode)
            os.chown(path, self._account.uid, self._account.gid)


def _validate_public_key(key: str) -> None:
    """Exactly one OpenSSH public key, checked by ssh-keygen itself."""
    if "PRIVATE KEY" in key:
        raise InvalidSshKeyError(PRIVATE_KEY_HINT)
    if "\n" in key:
        raise InvalidSshKeyError("Paste exactly one public key (one line).")
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        raise RuntimeError("ssh-keygen not found on PATH")
    result = (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [ssh_keygen, "-l", "-f", "/dev/stdin"],
            input=key,
            capture_output=True,
            text=True,
            check=False,
        )
    )
    if result.returncode != 0:
        raise InvalidSshKeyError(
            "That isn't a valid SSH public key. It should be one line starting "
            "with ssh-rsa or ssh-ed25519 — get it with: ssh-keygen -y -f private-key.pem"
        )
