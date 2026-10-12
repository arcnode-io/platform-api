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


def test_hmi_starts_behind_the_ingress_over_http(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()
    service = HmiService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        run=runner,
    )

    # Act
    result = service.apply()

    # Assert — both nginx answer; the page is done
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Serves the operator screen", True),
        ("Serves HTTP on port 80", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("hmi")
    # Assert — no certificate is generated; both services start together.
    assert not any(c.args[0] == "openssl" for c in runner.calls)
    up = next(c.args for c in runner.calls if "up" in c.args)
    assert up[-3:] == ["-d", "hmi", "https-ingress"]
