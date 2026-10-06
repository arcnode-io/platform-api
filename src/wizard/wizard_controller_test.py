"""HTTP-layer tests for the wizard controller — real requests through
FastAPI's request validation, not WizardService called directly."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wizard.wizard_fixtures import FakeProbe, account, ec2_style_pem
from src.wizard.wizard_module import WizardModule
from src.wizard.wizard_record import Deployment


def _client(tmp_path: Path, deployment: Deployment = Deployment.ON_PREM) -> TestClient:
    app = FastAPI()
    app.include_router(
        WizardModule(
            base_dir=tmp_path,
            account=account(tmp_path),
            deployment=deployment,
            run_probe=FakeProbe(),
        ).router
    )
    return TestClient(app)


def test_apply_with_your_public_key_returns_the_account(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
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
    client = _client(tmp_path)
    private_pem, _ = ec2_style_pem(tmp_path)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": private_pem})

    # Assert
    assert response.status_code == 400
    assert "ssh-keygen -y" in response.json()["detail"]


def test_wizard_page_404s_after_apply(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)
    client.post("/api/ssh", json={"ssh_public_key": public_key})

    # Act
    response = client.get("/")

    # Assert
    assert response.status_code == 404


def test_config_tells_the_ui_where_it_runs(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.get("/api/config")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"deployment": "cloud", "account": "joe"}


def test_cloud_has_no_ssh_route(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": "ssh-rsa AAAAx"})

    # Assert
    assert response.status_code == 404
