"""The on-prem Prometheus page: fetch its scrape config, start the container,
wait for its ready line, verify. Nothing to type."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

PROMETHEUS_SERVICE: Final[str] = "prometheus"
# Same file the cloud's UserData fetches from arcnode-public.
CONFIG_URL: Final[str] = "https://arcnode-public.s3.us-east-1.amazonaws.com/observability/prometheus.yml"
CONFIG_FILE: Final[str] = "observability/prometheus.yml"
DATA_DIR: Final[str] = "observability/prometheus-data"
READY_LINE: Final[str] = "Server is ready to receive web requests."
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs prometheus"


class PrometheusStepNotAvailableError(Exception):
    """No Prometheus page in the cloud — UserData starts it there."""


class PrometheusService:
    """Starts Prometheus with the cloud's scrape config."""

    def __init__(self, *, deployment: Deployment, tracker: StepTracker, ems_dir: Path, run: Runner) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._run = run

    def apply(self) -> StepResult:
        """Fetch, start, wait for ready, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise PrometheusStepNotAvailableError("no Prometheus page in the cloud")
        if self._tracker.is_done("prometheus"):
            raise StepAlreadyDoneError("Prometheus is already set up")
        (self._ems_dir / DATA_DIR).mkdir(parents=True, exist_ok=True)
        (self._ems_dir / "observability").mkdir(parents=True, exist_ok=True)
        self._run(Command(args=["curl", "-fsSL", CONFIG_URL, "-o", str(self._ems_dir / CONFIG_FILE)]))
        self._run(compose_command(self._ems_dir, "up", "-d", PROMETHEUS_SERVICE))
        wait_for_log(self._run, self._ems_dir, PROMETHEUS_SERVICE, READY_LINE)
        checks = [self._ready_check()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("prometheus")
        return StepResult(verified=verified, checks=checks)

    def _ready_check(self) -> VerifyCheck:
        logs = self._run(compose_command(self._ems_dir, "logs", PROMETHEUS_SERVICE)).stdout
        ready = READY_LINE in logs
        return VerifyCheck(
            name="Prometheus ready",
            ok=ready,
            detail="ready to receive web requests" if ready else "not ready yet",
            hint=LOG_HINT,
        )
