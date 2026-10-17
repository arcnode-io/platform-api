"""The on-prem Telemetry writer page: start the container on the arcnode
network, wait until it is subscribed to the broker, verify. Its password and
database URL were saved by the HiveMQ and PostgreSQL pages."""

from pathlib import Path

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.telemetry_writer_verify import (
    SUBSCRIBED_LINE,
    TELEMETRY_SERVICE,
    verify_telemetry,
)
from src.wizard.wizard_record import StepResult
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker


class TelemetryWriterService:
    """Starts the writer that persists every measurement to the timeseries database."""

    def __init__(
        self,
        *,
        tracker: StepTracker,
        ems_dir: Path,
        secrets_env_path: Path,
        run: Runner,
    ) -> None:
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._secrets_env_path = secrets_env_path
        self._run = run

    def apply(self) -> StepResult:
        """Start, wait for the subscription, verify — done only when every check passes."""
        if self._tracker.is_done("telemetry"):
            raise StepAlreadyDoneError("Telemetry writer is already set up")
        self._run(compose_command(self._ems_dir, "up", "-d", TELEMETRY_SERVICE))
        wait_for_log(self._run, self._ems_dir, TELEMETRY_SERVICE, SUBSCRIBED_LINE)
        checks = verify_telemetry(self._run, self._secrets_env_path, self._ems_dir)
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("telemetry")
        return StepResult(verified=verified, checks=checks)
