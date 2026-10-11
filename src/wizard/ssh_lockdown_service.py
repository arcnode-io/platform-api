"""The last on-prem page: SSH by key only. Password login stays on through setup
so a bad key can't lock anyone out; once the key page has proven the key, this
turns passwords off. Unchecking keeps them on — allowed, not recommended."""

from pathlib import Path
from typing import Final

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    Deployment,
    SshAccount,
    SshLockdownRequest,
    StepResult,
    VerifyCheck,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

DROPIN_FILE: Final[str] = "99-arcnode-key-only.conf"
DROPIN_TEXT: Final[str] = (
    "# Written by the ArcNode setup wizard: SSH by key only.\n"
    "PasswordAuthentication no\n"
    "KbdInteractiveAuthentication no\n"
)
RELOAD_COMMAND: Final[list[str]] = ["systemctl", "reload", "ssh"]
SETTING: Final[str] = "passwordauthentication"
KEEP_HINT: Final[str] = (
    "turn it off later: printf 'PasswordAuthentication no\\nKbdInteractiveAuthentication no\\n'"
    " | sudo tee /etc/ssh/sshd_config.d/99-arcnode-key-only.conf && sudo systemctl reload ssh"
)


class SshLockdownStepNotAvailableError(Exception):
    """No lockdown page in the cloud — EC2 never had password login."""


class SshKeyNotProvenError(Exception):
    """The key page hasn't passed yet; turning passwords off now could lock the person out."""


class SshLockdownService:
    """Turns SSH password login off once the customer's key is proven."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        account: SshAccount,
        sshd_config_dir: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._account = account
        self._sshd_config_dir = sshd_config_dir
        self._run = run

    def apply(self, request: SshLockdownRequest) -> StepResult:
        """Write the sshd drop-in, reload, verify — or record that passwords stay on."""
        if self._deployment == Deployment.CLOUD:
            raise SshLockdownStepNotAvailableError("no SSH lockdown page in the cloud")
        if self._tracker.is_done("ssh_lockdown"):
            raise StepAlreadyDoneError("SSH lockdown is already done")
        if not self._tracker.is_done("ssh"):
            raise SshKeyNotProvenError("add and verify your SSH key first")
        if not request.disable_password_login:
            checks = [
                VerifyCheck(
                    name="Password login kept",
                    ok=True,
                    detail="not recommended",
                    hint=KEEP_HINT,
                )
            ]
        else:
            self._sshd_config_dir.mkdir(parents=True, exist_ok=True)
            (self._sshd_config_dir / DROPIN_FILE).write_text(DROPIN_TEXT)
            self._run(Command(args=RELOAD_COMMAND))
            checks = [self._password_login_off()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("ssh_lockdown")
        return StepResult(verified=verified, checks=checks)

    def _password_login_off(self) -> VerifyCheck:
        """What sshd will actually do for this account, from sshd itself."""
        out = self._run(
            Command(
                args=[
                    "sshd",
                    "-T",
                    "-C",
                    f"user={self._account.name},host=localhost,addr=127.0.0.1",
                ]
            )
        )
        setting = next(
            (
                line
                for line in out.stdout.splitlines()
                if line.startswith(f"{SETTING} ")
            ),
            out.stdout.strip() or f"exit {out.returncode}",
        )
        return VerifyCheck(
            name="Password login off",
            ok=setting == f"{SETTING} no",
            detail=setting,
            hint=(
                f"sudo sshd -T -C user={self._account.name},host=localhost,addr=127.0.0.1"
                " | grep passwordauth; grep -ri passwordauth /etc/ssh/sshd_config"
                " /etc/ssh/sshd_config.d/"
            ),
        )
