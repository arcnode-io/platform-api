"""Unit tests for the on-prem Industrial gateway and HMI pages."""

from pathlib import Path

from src.wizard.hmi_service import HmiService
from src.wizard.industrial_gateway_service import IndustrialGatewayService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import Deployment


def test_industrial_gateway_starts_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = IndustrialGatewayService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=FakeRunner(),
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Industrial gateway running", True),
        ("Loaded the device spec", True),
        ("Subscribed to the broker", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("industrial_gateway")


def test_hmi_starts_and_serves_the_app(tmp_path: Path) -> None:
    # Arrange
    service = HmiService(
        deployment=Deployment.ON_PREM, tracker=tracker(tmp_path), ems_dir=tmp_path / "opt", run=FakeRunner()
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [("Serves the operator screen", True)]
    assert result.verified
    assert tracker(tmp_path).is_done("hmi")
