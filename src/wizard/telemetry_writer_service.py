"""The on-prem Telemetry writer page: save the customer's retention window,
start the container on the arcnode network, wait until it is subscribed to the
broker, verify. Its password and database URL were saved by the HiveMQ and
PostgreSQL pages."""

from pathlib import Path
from typing import Final

import yaml

from src.customer_inputs import TELEMETRY_RETENTION_DAYS

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.telemetry_writer_verify import (
    SUBSCRIBED_LINE,
    TELEMETRY_SERVICE,
    verify_telemetry,
)
from src.wizard.wizard_record import StepResult, TelemetryRequest
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

# The compose file mounts this into the writer as its cfg.customer.yml.
OVERLAY_FILE: Final[str] = "telemetry-writer-cfg.customer.yml"


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

    def apply(self, request: TelemetryRequest) -> StepResult:
        """Save the window, start, wait for the subscription, verify — done only
        when every check passes."""
        if self._tracker.is_done("telemetry"):
            raise StepAlreadyDoneError("Telemetry writer is already set up")
        self._ems_dir.mkdir(parents=True, exist_ok=True)
        (self._ems_dir / OVERLAY_FILE).write_text(
            yaml.safe_dump({TELEMETRY_RETENTION_DAYS.cfg_key: request.retention_days})
        )
        # Reason: a retry with a new window must restart the writer; `up -d` alone keeps it running.
        self._run(
            compose_command(
                self._ems_dir, "up", "-d", "--force-recreate", TELEMETRY_SERVICE
            )
        )
        wait_for_log(self._run, self._ems_dir, TELEMETRY_SERVICE, SUBSCRIBED_LINE)
        checks = verify_telemetry(
            self._run, self._secrets_env_path, self._ems_dir, request.retention_days
        )
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("telemetry")
        return StepResult(verified=verified, checks=checks)
