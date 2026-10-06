"""Unit tests for the SSH step's verification gate — checks, fingerprint,
and the wizard staying open (and retry-safe) when a check fails."""

from pathlib import Path

from src.wizard.wizard_fixtures import (
    FakeProbe,
    ec2_style_pem,
    make_service,
    ssh_keygen,
)
from src.wizard.wizard_record import ApplyRequest, CommandOutput


def test_apply_verifies_ssh_and_shows_your_key_fingerprint(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)
    expected_fingerprint = ssh_keygen("-l", "-f", str(tmp_path / "my-key.pem")).split()[
        1
    ]

    # Act
    result = service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert
    actual_rows = [(check.name, check.ok) for check in result.checks]
    assert actual_rows == [
        ("SSH daemon running", True),
        ("Answers SSH on port 22", True),
        ("Key login allowed for joe", True),
        ("Your key is installed", True),
    ]
    assert expected_fingerprint in result.checks[3].detail
    assert result.verified
    assert service.is_applied()


def test_failed_check_keeps_the_wizard_open(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    probe = FakeProbe()
    probe.outputs["systemctl"] = CommandOutput(returncode=3, stdout="inactive\n")
    service = make_service(tmp_path, probe=probe)

    # Act
    result = service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert: the gate holds — nothing marked applied, debug hint offered
    assert not result.verified
    assert (result.checks[0].ok, result.checks[0].detail) == (False, "inactive")
    assert result.checks[0].hint == "sudo systemctl status ssh && sudo sshd -t"
    assert not service.is_applied()


def test_retry_after_a_failed_check_does_not_add_the_key_twice(tmp_path: Path) -> None:
    # Arrange: first try fails verification, then sshd gets fixed
    _, public_key = ec2_style_pem(tmp_path)
    probe = FakeProbe()
    probe.outputs["systemctl"] = CommandOutput(returncode=3, stdout="inactive\n")
    service = make_service(tmp_path, probe=probe)
    service.apply(ApplyRequest(ssh_public_key=public_key))
    probe.outputs["systemctl"] = CommandOutput(returncode=0, stdout="active\n")

    # Act
    result = service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert
    authorized = (tmp_path / "home" / "joe" / ".ssh" / "authorized_keys").read_text()
    assert authorized.splitlines() == [public_key]
    assert result.verified


def test_every_check_says_what_to_run_when_it_fails(tmp_path: Path) -> None:
    # Arrange
    _, public_key = ec2_style_pem(tmp_path)
    service = make_service(tmp_path)

    # Act
    result = service.apply(ApplyRequest(ssh_public_key=public_key))

    # Assert: one console command per failure mode, aimed at that check
    actual_hints = {check.name: check.hint for check in result.checks}
    assert actual_hints == {
        "SSH daemon running": "sudo systemctl status ssh && sudo sshd -t",
        "Answers SSH on port 22": "sudo ss -ltnp | grep sshd; sudo journalctl -u ssh",
        "Key login allowed for joe": (
            "sudo sshd -T -C user=joe,host=localhost,addr=127.0.0.1 | grep pubkey; "
            "grep -ri pubkey /etc/ssh/sshd_config /etc/ssh/sshd_config.d/"
        ),
        "Your key is installed": (
            "sudo ls -la ~joe/.ssh; sudo cat ~joe/.ssh/authorized_keys"
        ),
    }
