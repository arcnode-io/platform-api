"""Unit tests for the on-prem Telemetry writer page — started on the arcnode
network once it is subscribed to the broker, with its database URL present."""

from pathlib import Path

import yaml

from src.wizard.telemetry_writer_service import TelemetryWriterService
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import TelemetryRequest


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
    result = service.apply(TelemetryRequest(retention_days=7))

    # Assert
    actual_rows = [(check.name, check.ok) for check in result.checks]
    assert actual_rows == [
        ("Telemetry writer running", True),
        ("Subscribed to the measurements", True),
        ("Timeseries database saved", True),
        ("Keeps 7 days of measurements", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("telemetry")


def test_apply_hands_the_customers_window_to_the_writer(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["logs telemetry-writer"] = ok(
        "measurements retention: 30 days\nsubscribed (reason_code=Success)\n"
    )
    service = make_telemetry_service(tmp_path, runner)

    # Act
    result = service.apply(TelemetryRequest(retention_days=30))

    # Assert
    overlay = tmp_path / "opt" / "telemetry-writer-cfg.customer.yml"
    assert yaml.safe_load(overlay.read_text()) == {"retention_days": 30}
    assert result.verified


def test_a_window_the_writer_did_not_apply_fails_the_page(tmp_path: Path) -> None:
    # Arrange: the writer is still on an older window
    runner = FakeRunner()
    runner.queries["logs telemetry-writer"] = ok(
        "measurements retention: 7 days\nsubscribed (reason_code=Success)\n"
    )
    service = make_telemetry_service(tmp_path, runner)

    # Act
    result = service.apply(TelemetryRequest(retention_days=30))

    # Assert
    assert not result.verified
    assert result.checks[-1].name == "Keeps 30 days of measurements"
    assert not result.checks[-1].ok
