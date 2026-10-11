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
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        run=FakeRunner(),
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
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        run=FakeRunner(),
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("MLflow tracking server listening", True)
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("mlflow")


def test_prometheus_data_dir_is_owned_by_the_prometheus_user(tmp_path: Path) -> None:
    """The Prometheus image runs as uid 65534; a root-owned data dir makes it crash-loop."""
    # Arrange
    runner = FakeRunner()
    service = PrometheusService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        run=runner,
    )

    # Act
    service.apply()

    # Assert
    chowns = [c.args for c in runner.calls if c.args[:1] == ["chown"]]
    assert [
        "chown",
        "-R",
        "65534:65534",
        str(tmp_path / "opt" / "observability" / "prometheus-data"),
    ] in chowns
