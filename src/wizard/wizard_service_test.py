"""Unit tests for WizardService's SSH step — on-prem only: bring your own
key. In the cloud the step doesn't exist (EC2 already set up SSH)."""

from pathlib import Path

import pytest

from src.wizard.wizard_fixtures import ec2_style_pem, make_service
from src.wizard.wizard_record import ApplyRequest, Deployment
from src.wizard.wizard_service import (
    InvalidSshKeyError,
    SshStepNotAvailableError,
    WizardAlreadyAppliedError,
)


def test_apply_authorizes_the_public_half_of_your_pem(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)

    # Act
    result = service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert
    authorized_keys = tmp_path / "home" / "joe" / ".ssh" / "authorized_keys"
    assert authorized_keys.read_text() == public_key + "\n"
    assert result.account == "joe"


def test_apply_sets_permissions_sshd_requires(tmp_path: Path) -> None:
    # Arrange: sshd's StrictModes ignores keys in group/world-writable paths
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)

    # Act
    service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert
    ssh_dir = tmp_path / "home" / "joe" / ".ssh"
    actual_modes = (
        ssh_dir.stat().st_mode & 0o777,
        (ssh_dir / "authorized_keys").stat().st_mode & 0o777,
    )
    assert actual_modes == (0o700, 0o600)


def test_apply_keeps_keys_already_in_authorized_keys(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)
    ssh_dir = tmp_path / "home" / "joe" / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "authorized_keys").write_text("ssh-ed25519 AAAAexisting old@key\n")

    # Act
    service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert
    actual = (ssh_dir / "authorized_keys").read_text().splitlines()
    assert actual == ["ssh-ed25519 AAAAexisting old@key", public_key]


def test_apply_refuses_the_pem_itself_with_a_hint(tmp_path: Path) -> None:
    # Arrange: pasting the private .pem would leak it — refuse, show the fix
    private_pem, _ = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)

    # Act / Assert
    with pytest.raises(InvalidSshKeyError, match="ssh-keygen -y"):
        service.apply(ApplyRequest(ssh_public_key=private_pem))


def test_apply_refuses_text_that_is_not_a_public_key(tmp_path: Path) -> None:
    # Arrange
    service = make_service(tmp_path)

    # Act / Assert
    with pytest.raises(InvalidSshKeyError):
        service.apply(ApplyRequest(ssh_public_key="ssh-rsa not-base64-garbage"))


def test_cloud_has_no_ssh_step(tmp_path: Path) -> None:
    # Arrange: EC2 already put the launch key pair in authorized_keys
    service = make_service(tmp_path, deployment=Deployment.CLOUD)
    ssh_dir = tmp_path / "home" / "joe" / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "authorized_keys").write_text("ssh-rsa AAAAec2launchkey my-ec2-key\n")

    # Act / Assert: refused outright, and EC2's key is untouched
    with pytest.raises(SshStepNotAvailableError):
        service.apply(ApplyRequest(ssh_public_key="ssh-rsa AAAAanything"))
    actual = (ssh_dir / "authorized_keys").read_text()
    assert actual == "ssh-rsa AAAAec2launchkey my-ec2-key\n"


def test_apply_marks_applied_and_second_call_raises(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)
    service.apply(ApplyRequest(ssh_public_key=public_key))

    # Act / Assert
    assert service.is_applied()
    with pytest.raises(WizardAlreadyAppliedError):
        service.apply(ApplyRequest(ssh_public_key=public_key))
