"""HTTP-layer tests for the wizard controller — real requests through
FastAPI's request validation, not the services called directly."""

import json
from pathlib import Path

import pytest

from src.wizard.controller_fixtures import wizard_client
from src.wizard.wizard_fixtures import FakeRunner, ec2_style_pem, ok
from src.wizard.wizard_record import Deployment

DEVICE_API_SECRETS: dict[str, str] = {
    "jwt_secret": "x" * 40,
    "operator_password": "Operator-pw-1!",
    "viewer_password": "Viewer-pw-1!",
}
ANALYST_SERVER_KEYS: dict[str, str] = {
    "openweathermap_api_key": "owm-key-1234",
    "gridstatus_api_key": "grid-key-1234",
}
BROKER_PASSWORDS: dict[str, str] = {
    "service": "Service-pw-1!",
    "operator": "Operator-pw-1!",
    "viewer": "Viewer-pw-1!",
}


def test_hardware_check_returns_every_row_with_its_debug_command(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()
    runner.outputs["findmnt"] = ok("/dev/sda2 1000202273280\n")
    runner.outputs["lsblk"] = ok("part \ndisk sata\n")
    client = wizard_client(tmp_path, runner=runner)

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


def test_cloud_closes_once_the_passwords_are_set(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD)

    # Act — the hardware check alone doesn't close the cloud wizard
    assert client.post("/api/preflight").json()["verified"] is True
    still_open = client.get("/").status_code

    # Act — the customer's passwords do
    secrets = client.post(
        "/api/cloud-secrets",
        json={
            "operator_password": "Operator-pw-1!",
            "viewer_password": "Viewer-pw-1!",
            "grafana_password": "Grafana-pw-1!",
        },
    )

    # Assert
    assert still_open == 200
    assert secrets.json()["verified"] is True
    assert client.get("/").status_code == 404


def test_wizard_stays_open_after_ssh_and_reports_it_done(tmp_path: Path) -> None:
    # Arrange: SSH is only the second on-prem page
    client = wizard_client(tmp_path)
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
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.get("/api/config")

    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "deployment": "cloud",
        "badge": "☁️ Commercial",
        "account": "joe",
        "completed": [],
    }


def test_wizard_closes_once_every_on_prem_page_is_done(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)
    _, public_key = ec2_style_pem(tmp_path)
    client.post("/api/preflight")
    client.post("/api/ssh", json={"ssh_public_key": public_key})
    client.post("/api/docker")
    client.post("/api/postgres", json={"password": "Pg-pass1!"})
    client.post("/api/neo4j", json={"password": "Ne-4jpass1!"})
    # Ollama streams NDJSON — progress lines, then the result
    ollama = client.post("/api/ollama")

    site = client.post("/api/site")
    # Act: the last page
    hivemq = client.post("/api/hivemq", json=BROKER_PASSWORDS)
    telemetry = client.post("/api/telemetry")
    prometheus = client.post("/api/prometheus")
    mlflow = client.post("/api/mlflow")
    analyst_model = client.post("/api/analyst-model")
    analyst_server = client.post("/api/analyst-server", json=ANALYST_SERVER_KEYS)
    device_api = client.post("/api/device-api", json=DEVICE_API_SECRETS)
    der_control = client.post("/api/der-control", json={"utility_mirror_url": None})
    gateway = client.post("/api/industrial-gateway")
    hmi = client.post("/api/hmi")
    grafana = client.post("/api/grafana", json={"password": "Grafana-pw-1!"})

    # Assert
    lines = [json.loads(line) for line in ollama.text.splitlines()]
    assert ollama.headers["content-type"] == "application/x-ndjson"
    assert lines[0]["progress"]["model"] == "gemma4:26b"
    assert lines[-1]["result"]["verified"] is True
    assert site.json()["verified"] is True
    assert hivemq.json()["verified"] is True
    assert telemetry.json()["verified"] is True
    assert prometheus.json()["verified"] is True
    assert mlflow.json()["verified"] is True
    assert analyst_model.json()["verified"] is True
    assert analyst_server.json()["verified"] is True
    assert device_api.json()["verified"] is True
    assert der_control.json()["verified"] is True
    assert gateway.json()["verified"] is True
    assert hmi.json()["verified"] is True
    assert grafana.json()["verified"] is True
    assert client.get("/").status_code == 404


def test_docker_page_reports_the_range_docker_picked(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path)

    # Act
    response = client.post("/api/docker")

    # Assert
    assert response.status_code == 200
    assert response.json()["checks"][1]["detail"] == "172.23.0.0/16, gateway 172.23.0.1"


def test_cloud_has_no_hivemq_route(tmp_path: Path) -> None:
    # Arrange: UserData starts the broker in the cloud
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD)
    # Act
    response = client.post("/api/hivemq", json=BROKER_PASSWORDS)

    # Assert
    assert response.status_code == 404


@pytest.mark.parametrize(
    "route", ["/api/docker", "/api/postgres", "/api/neo4j", "/api/ollama", "/api/site"]
)
def test_cloud_has_no_daemon_routes(tmp_path: Path, route: str) -> None:
    # Arrange: EC2 sets up Docker; databases + LLM are managed services
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD)

    # Act
    response = client.post(route, json={"password": "Pg-pass1!"})

    # Assert
    assert response.status_code == 404


def test_wizard_files_are_revalidated_on_every_load(tmp_path: Path) -> None:
    # Arrange: a re-flashed box usually comes back on the same DHCP address,
    # and a browser that cached the old wizard's JSX would mix versions
    client = wizard_client(tmp_path)

    # Act
    page = client.get("/")
    asset = client.get("/daemon-pages.jsx")

    # Assert
    assert page.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "no-cache"


def test_der_control_can_be_skipped_so_setup_continues(tmp_path: Path) -> None:
    # Arrange — no utility link yet
    client = wizard_client(tmp_path)

    # Act
    response = client.post("/api/der-control/skip")

    # Assert
    assert response.json()["verified"] is True
