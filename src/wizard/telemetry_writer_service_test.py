"""Unit tests for the on-prem Telemetry writer page — started on the arcnode
network once it is subscribed to the broker, with its database URL present."""

from pathlib import Path

from src.wizard.telemetry_writer_service import TelemetryWriterService
from src.wizard.wizard_fixtures import FakeRunner, tracker


def make_telemetry_service(
    tmp_path: Path, runner: FakeRunner
) -> TelemetryWriterService:
    """A service on tmp_path with the Postgres URL already saved by its page."""
    (tmp_path / "secrets.env").write_text("TIMESERIES_URL=postgres://x\n")
    return TelemetryWriterService(
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )


def test_apply_starts_the_writer_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_telemetry_service(tmp_path, FakeRunner())

    # Act
    result = service.apply()

    # Assert
    actual_rows = [(check.name, check.ok) for check in result.checks]
    assert actual_rows == [
        ("Telemetry writer running", True),
        ("Subscribed to the measurements", True),
        ("Timeseries database saved", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("telemetry")
