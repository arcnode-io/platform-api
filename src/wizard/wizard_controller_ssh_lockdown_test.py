"""HTTP-layer tests for the last on-prem page: key-only SSH, refused until the
key page has passed."""

from pathlib import Path

from src.wizard.controller_fixtures import wizard_client
from src.wizard.wizard_fixtures import ec2_style_pem


def test_lockdown_is_409_until_the_key_page_has_passed(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)

    # Act
    response = client.post("/api/ssh-lockdown", json={"disable_password_login": True})

    # Assert
    assert response.status_code == 409
    assert "key" in response.json()["detail"]


def test_lockdown_after_the_key_page_turns_passwords_off(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)
    assert client.post("/api/ssh", json={"ssh_public_key": public_key}).json()[
        "verified"
    ]

    # Act
    response = client.post("/api/ssh-lockdown", json={"disable_password_login": True})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["verified"]
    assert [(c["name"], c["ok"]) for c in body["checks"]] == [
        ("Password login off", True)
    ]
    assert (
        "PasswordAuthentication no"
        in (tmp_path / "sshd_config.d" / "99-arcnode-key-only.conf").read_text()
    )
