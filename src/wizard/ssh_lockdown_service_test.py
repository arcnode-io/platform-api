"""The last on-prem page: SSH by key only. Password login stayed on through
setup so a bad key couldn't lock anyone out; with the key proven, this turns
it off — unless the person unchecks it, which is their call."""

from pathlib import Path

import pytest

from src.wizard.ssh_lockdown_service import (
    DROPIN_FILE,
    SshKeyNotProvenError,
    SshLockdownService,
)
from src.wizard.wizard_fixtures import FakeRunner, account, ok, tracker
from src.wizard.wizard_record import Deployment, SshLockdownRequest


def _service(
    tmp_path: Path, runner: FakeRunner, *, key_done: bool = True
) -> SshLockdownService:
    steps = tracker(tmp_path)
    if key_done:
        steps.mark_done("ssh")
    return SshLockdownService(
        deployment=Deployment.ON_PREM,
        tracker=steps,
        account=account(tmp_path),
        sshd_config_dir=tmp_path / "sshd_config.d",
        run=runner,
    )


def test_apply_turns_password_login_off_reloads_sshd_and_verifies(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()
    service = _service(tmp_path, runner)

    # Act
    result = service.apply(SshLockdownRequest(disable_password_login=True))

    # Assert
    dropin = tmp_path / "sshd_config.d" / DROPIN_FILE
    assert "PasswordAuthentication no" in dropin.read_text()
    assert ["systemctl", "reload", "ssh"] in [c.args for c in runner.calls]
    assert [(c.name, c.ok) for c in result.checks] == [("Password login off", True)]
    assert result.verified
    assert tracker(tmp_path).is_done("ssh_lockdown")


def test_apply_can_keep_password_login_and_says_so(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = _service(tmp_path, runner)

    # Act
    result = service.apply(SshLockdownRequest(disable_password_login=False))

    # Assert
    assert not (tmp_path / "sshd_config.d" / DROPIN_FILE).exists()
    assert ["systemctl", "reload", "ssh"] not in [c.args for c in runner.calls]
    assert [(c.name, c.ok) for c in result.checks] == [("Password login kept", True)]
    assert result.verified
    assert tracker(tmp_path).is_done("ssh_lockdown")


def test_apply_refuses_before_the_key_page_is_done(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeRunner(), key_done=False)

    # Act + Assert
    with pytest.raises(SshKeyNotProvenError):
        service.apply(SshLockdownRequest(disable_password_login=True))


def test_apply_stays_open_while_sshd_still_allows_passwords(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.outputs["sshd"] = ok("port 22\npasswordauthentication yes\n")
    service = _service(tmp_path, runner)

    # Act
    result = service.apply(SshLockdownRequest(disable_password_login=True))

    # Assert
    assert [(c.name, c.ok, c.detail) for c in result.checks] == [
        ("Password login off", False, "passwordauthentication yes")
    ]
    assert not result.verified
    assert not tracker(tmp_path).is_done("ssh_lockdown")
