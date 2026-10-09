"""HTTP-layer tests for the wizard controller — real requests through
FastAPI's request validation, not WizardService called directly."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wizard.wizard_fixtures import FakeRunner, account, ec2_style_pem, ok
from src.wizard.wizard_module import WizardModule
from src.wizard.wizard_record import Deployment, HardwareMinimums, WizardConfig


def _client(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    runner: FakeRunner | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        WizardModule(
            base_dir=tmp_path,
            secrets_env_path=tmp_path / "secrets.env",
            account=account(tmp_path),
            config=WizardConfig(
                deployment=deployment,
                hardware=HardwareMinimums(
                    vcpus=8, memory_gib=64, gpus=1, gpu_memory_gb=48, disk_gb=1000
                ),
            ),
            run=runner or FakeRunner(),
        ).router
    )
    return TestClient(app)


def test_hardware_check_returns_every_row_with_its_debug_command(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()
    runner.outputs["findmnt"] = ok("/dev/sda2 1000202273280\n")
    runner.outputs["lsblk"] = ok("part \ndisk sata\n")
    client = _client(tmp_path, runner=runner)

    # Act
    response = client.post("/api/preflight")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["verified"] is False
    assert body["checks"][4] == {
        "name": "Data disk",
        "ok": False,
        "detail": "SATA, 1000 GB (need NVMe ≥ 1000 GB)",
        "hint": "findmnt --target /var/lib; lsblk -o NAME,TRAN,ROTA,SIZE",
    }


def test_cloud_closes_once_the_hardware_check_passes(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post("/api/preflight")

    # Assert
    assert response.json()["verified"] is True
    assert client.get("/").status_code == 404


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


def test_wizard_stays_open_after_ssh_and_reports_it_done(tmp_path: Path) -> None:
    # Arrange: SSH is only the second on-prem page
    client = _client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)
    client.post("/api/preflight")
    client.post("/api/ssh", json={"ssh_public_key": public_key})

    # Act
    page = client.get("/")
    config = client.get("/api/config")

    # Assert: a reload resumes past SSH
    assert page.status_code == 200
    assert config.json()["completed"] == ["preflight", "ssh"]


def test_config_tells_the_ui_where_it_runs(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.get("/api/config")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"deployment": "cloud", "account": "joe", "completed": []}


def test_cloud_has_no_ssh_route(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post("/api/ssh", json={"ssh_public_key": "ssh-rsa AAAAx"})

    # Assert
    assert response.status_code == 404


def test_wizard_closes_once_every_on_prem_page_is_done(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)
    client.post("/api/preflight")
    client.post("/api/ssh", json={"ssh_public_key": public_key})
    client.post("/api/docker")
    client.post("/api/postgres", json={"password": "Pg-pass1!"})

    # Act
    response = client.post("/api/neo4j", json={"password": "Ne-4jpass1!"})

    # Assert
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert client.get("/").status_code == 404


def test_docker_page_reports_the_range_docker_picked(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)

    # Act
    response = client.post("/api/docker")

    # Assert
    assert response.status_code == 200
    assert response.json()["checks"][1]["detail"] == "172.23.0.0/16, gateway 172.23.0.1"


@pytest.mark.parametrize("route", ["/api/docker", "/api/postgres", "/api/neo4j"])
def test_cloud_has_no_daemon_routes(tmp_path: Path, route: str) -> None:
    # Arrange: EC2 sets up Docker; the cloud's databases are managed services
    client = _client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post(route, json={"password": "Pg-pass1!"})

    # Assert
    assert response.status_code == 404


def test_wizard_files_are_revalidated_on_every_load(tmp_path: Path) -> None:
    # Arrange: a re-flashed box usually comes back on the same DHCP address,
    # and a browser that cached the old wizard's JSX would mix versions
    client = _client(tmp_path)

    # Act
    page = client.get("/")
    asset = client.get("/daemon-pages.jsx")

    # Assert
    assert page.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "no-cache"
