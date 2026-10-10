"""Unit tests for the on-prem Prometheus and MLflow pages — each starts its
container and is done once its own readiness line is in the log."""

from pathlib import Path

from src.wizard.mlflow_service import MlflowService
from src.wizard.prometheus_service import PrometheusService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import Deployment


def test_prometheus_starts_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = PrometheusService(
        deployment=Deployment.ON_PREM, tracker=tracker(tmp_path), ems_dir=tmp_path / "opt", run=FakeRunner()
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [("Prometheus ready", True)]
    assert result.verified
    assert tracker(tmp_path).is_done("prometheus")


def test_mlflow_starts_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = MlflowService(
        deployment=Deployment.ON_PREM, tracker=tracker(tmp_path), ems_dir=tmp_path / "opt", run=FakeRunner()
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [("MLflow tracking server listening", True)]
    assert result.verified
    assert tracker(tmp_path).is_done("mlflow")
