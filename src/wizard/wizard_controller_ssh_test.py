"""HTTP-layer tests for the SSH page — the key round-trips through
FastAPI's request validation."""

from pathlib import Path

from src.wizard.controller_fixtures import wizard_client
from src.wizard.wizard_fixtures import ec2_style_pem
from src.wizard.wizard_record import Deployment


def test_apply_with_your_public_key_returns_the_account(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": public_key})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert (body["verified"], body["account"]) == (True, "joe")
    assert [check["ok"] for check in body["checks"]] == [True, True, True, True]


def test_apply_with_the_pem_itself_is_400_with_a_hint(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)
    private_pem, _ = ec2_style_pem(tmp_path)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": private_pem})

    # Assert
    assert response.status_code == 400
    assert "ssh-keygen -y" in response.json()["detail"]


def test_cloud_has_no_ssh_route(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": "ssh-rsa AAAAx"})

    # Assert
    assert response.status_code == 404
