"""The on-prem MLflow page: create its data dirs, start the tracking server,
wait for its listening line, verify. Nothing to type."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

MLFLOW_SERVICE: Final[str] = "mlflow"
# The line the current mlflow image prints once uvicorn is serving (the old
# "Listening at:" line never appears on ghcr.io/mlflow/mlflow:latest).
LISTENING_LINE: Final[str] = "Uvicorn running on http://0.0.0.0:5000"
LOG_HINT: Final[str] = (
    "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs mlflow"
)
DATA_DIRS: Final[tuple[str, ...]] = ("mlflow/mlflow-data", "mlflow/mlflow-artifacts")


class MlflowService:
    """Starts the experiment tracker the analyst model logs its forecasts to."""

    def __init__(
        self,
        *,
        tracker: StepTracker,
        ems_dir: Path,
        run: Runner,
    ) -> None:
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._run = run

    def apply(self) -> StepResult:
        """Make its dirs, start, wait for listening, verify — done only when every check passes."""
        if self._tracker.is_done("mlflow"):
            raise StepAlreadyDoneError("MLflow is already set up")
        for directory in DATA_DIRS:
            (self._ems_dir / directory).mkdir(parents=True, exist_ok=True)
        self._run(compose_command(self._ems_dir, "up", "-d", MLFLOW_SERVICE))
        wait_for_log(self._run, self._ems_dir, MLFLOW_SERVICE, LISTENING_LINE)
        checks = [self._listening_check()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("mlflow")
        return StepResult(verified=verified, checks=checks)

    def _listening_check(self) -> VerifyCheck:
        logs = self._run(compose_command(self._ems_dir, "logs", MLFLOW_SERVICE)).stdout
        listening = LISTENING_LINE in logs
        return VerifyCheck(
            name="MLflow tracking server listening",
            ok=listening,
            detail="listening on port 5000" if listening else "not listening yet",
            hint=LOG_HINT,
        )
