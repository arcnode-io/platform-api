"""The on-prem analyst model page: write its overlay from the order's site,
start the daily scheduler on the arcnode network, verify. Nothing to type."""

from pathlib import Path
from typing import Final

import yaml

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.ems_cfg import ANALYST_MODEL_CFG_FILE, AnalystModelCfg, write_yaml
from src.wizard.order_record import SITE_FILE, OrderSite
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

ANALYST_MODEL_SERVICE: Final[str] = "analyst-model"
# Same MLflow address the cloud's UserData writes; the compose network name.
MLFLOW_URI: Final[str] = "http://mlflow:5000"
# Logged after the model's startup MLflow probe passes; a bad address exits the container before this.
READY_LINE: Final[str] = f"MLflow healthy at {MLFLOW_URI}"
SCHEDULER_LINE: Final[str] = "Scheduler started"
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs analyst-model"


class AnalystModelStepNotAvailableError(Exception):
    """No analyst model page in the cloud — UserData starts it there."""


class AnalystModelService:
    """Starts the model that trains and publishes the daily price forecast."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        order_dir: Path,
        ems_dir: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._order_dir = order_dir
        self._ems_dir = ems_dir
        self._run = run

    def apply(self) -> StepResult:
        """Write the overlay, start, wait for the scheduler, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise AnalystModelStepNotAvailableError("no analyst model page in the cloud")
        if self._tracker.is_done("analyst_model"):
            raise StepAlreadyDoneError("the analyst model is already set up")
        site = OrderSite.model_validate(yaml.safe_load((self._order_dir / SITE_FILE).read_text()))
        expected = AnalystModelCfg(site_id=site.site_id, mlflow_tracking_uri=MLFLOW_URI)
        write_yaml(self._ems_dir / ANALYST_MODEL_CFG_FILE, expected)
        self._run(compose_command(self._ems_dir, "up", "-d", ANALYST_MODEL_SERVICE))
        wait_for_log(self._run, self._ems_dir, ANALYST_MODEL_SERVICE, READY_LINE)
        checks = [
            self._running_check(),
            self._scheduler_check(),
            self._mlflow_check(),
            self._saved_check(expected),
        ]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("analyst_model")
        return StepResult(verified=verified, checks=checks)

    def _running_check(self) -> VerifyCheck:
        out = self._run(compose_command(self._ems_dir, "ps", "-q", "--status", "running", ANALYST_MODEL_SERVICE))
        running = bool(out.stdout.strip())
        return VerifyCheck(
            name="Analyst model container running",
            ok=running,
            detail="running" if running else "not running",
            hint=LOG_HINT,
        )

    def _scheduler_check(self) -> VerifyCheck:
        logs = self._run(compose_command(self._ems_dir, "logs", ANALYST_MODEL_SERVICE)).stdout
        started = SCHEDULER_LINE in logs
        return VerifyCheck(
            name="Scheduler started",
            ok=started,
            detail="daily run scheduled" if started else "no scheduler line yet",
            hint=LOG_HINT,
        )

    def _mlflow_check(self) -> VerifyCheck:
        """Probe the MLflow address from the arcnode network, the same way the
        analyst model will reach it. The file check only proves what was written."""
        out = self._run(
            Command(
                args=["docker", "run", "--rm", "--network", DOCKER_NETWORK, "curlimages/curl",
                      "-fsS", f"{MLFLOW_URI}/health"]
            )
        )
        reachable = out.returncode == 0
        return VerifyCheck(
            name="MLflow reachable from the analyst model",
            ok=reachable,
            detail=MLFLOW_URI if reachable else f"exit {out.returncode}",
            hint="sudo docker compose -f /opt/arcnode/docker-compose.yaml logs mlflow",
        )

    def _saved_check(self, expected: AnalystModelCfg) -> VerifyCheck:
        """Read the file back — what the container will actually mount."""
        path = self._ems_dir / ANALYST_MODEL_CFG_FILE
        saved = AnalystModelCfg.model_validate(yaml.safe_load(path.read_text())) == expected
        return VerifyCheck(
            name="Saved for the analyst model",
            ok=saved,
            detail=str(path) if saved else "missing or different",
            hint=f"sudo cat {path}",
        )
