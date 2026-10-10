"""The on-prem analyst server page: save the two API keys the customer sets,
start the server once uvicorn is listening, verify its health route. Nothing
else to type; the Device API it reads from is already up."""

from pathlib import Path
from typing import Final

from src.wizard.analyst_server_progress import StageProgress, stage_status
from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.secrets_env import save_secrets, saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import AnalystServerKeys, Command, Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

ANALYST_SERVER_SERVICE: Final[str] = "analyst-server"
# Logged by uvicorn once the server is listening on the container's port 8000.
READY_LINE: Final[str] = "Uvicorn running on http://0.0.0.0:8000"
HEALTH_URL: Final[str] = "http://analyst-server:8000/health"
# Same curl image the other pages probe with.
PROBE_IMAGE: Final[str] = "curlimages/curl"
SAVED_NAMES: Final[list[str]] = ["OPENWEATHERMAP_API_KEY", "GRIDSTATUS_API_KEY"]
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs analyst-server"


class AnalystServerStepNotAvailableError(Exception):
    """No analyst server page in the cloud — UserData starts it there."""


class AnalystServerService:
    """Starts the analyst server the HMI chats with."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        ems_dir: Path,
        secrets_env_path: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._secrets_env_path = secrets_env_path
        self._run = run

    def apply(self, request: AnalystServerKeys) -> StepResult:
        """Save the keys, start, wait for uvicorn, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise AnalystServerStepNotAvailableError("no analyst server page in the cloud")
        if self._tracker.is_done("analyst_server"):
            raise StepAlreadyDoneError("the analyst server is already set up")
        # Reason: compose reads the env file itself, so the keys go in before `up`.
        save_secrets(
            self._secrets_env_path,
            {
                "OPENWEATHERMAP_API_KEY": request.openweathermap_api_key,
                "GRIDSTATUS_API_KEY": request.gridstatus_api_key,
            },
        )
        self._run(compose_command(self._ems_dir, "up", "-d", ANALYST_SERVER_SERVICE))
        wait_for_log(self._run, self._ems_dir, ANALYST_SERVER_SERVICE, READY_LINE)
        checks = [
            self._running_check(),
            self._health_check(),
            saved_check(self._secrets_env_path, SAVED_NAMES),
        ]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("analyst_server")
        return StepResult(verified=verified, checks=checks)

    def progress(self) -> list[StageProgress]:
        """Each startup stage, read from the container's own log lines."""
        logs = self._run(compose_command(self._ems_dir, "logs", ANALYST_SERVER_SERVICE)).stdout
        return stage_status(logs)

    def _running_check(self) -> VerifyCheck:
        out = self._run(compose_command(self._ems_dir, "ps", "-q", "--status", "running", ANALYST_SERVER_SERVICE))
        running = bool(out.stdout.strip())
        return VerifyCheck(
            name="Analyst server running",
            ok=running,
            detail="running" if running else "not running",
            hint=LOG_HINT,
        )

    def _health_check(self) -> VerifyCheck:
        out = self._run(
            Command(args=["docker", "run", "--rm", "--network", DOCKER_NETWORK, PROBE_IMAGE, "-fsS", "-o", "/dev/null", HEALTH_URL])
        )
        ok = out.returncode == 0
        return VerifyCheck(
            name="Analyst server health",
            ok=ok,
            detail="/health answers" if ok else f"/health failed (curl exit {out.returncode})",
            hint=LOG_HINT,
        )
