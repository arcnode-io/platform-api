"""The on-prem HMI page: start the operator screen on port 80, wait for nginx
to be up, verify it serves the app. Nothing to type."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

HMI_SERVICE: Final[str] = "hmi"
# nginx logs this once its workers are up.
READY_LINE: Final[str] = "start worker processes"
PROBE_IMAGE: Final[str] = "curlimages/curl"
HMI_URL: Final[str] = "http://hmi/"
LOG_HINT: Final[str] = (
    "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs hmi"
)


class HmiStepNotAvailableError(Exception):
    """No HMI page in the cloud — UserData starts it there."""


class HmiService:
    """Starts the operator screen that the box's browsers open."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        ems_dir: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._run = run

    def apply(self) -> StepResult:
        """Start, wait for nginx, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise HmiStepNotAvailableError("no HMI page in the cloud")
        if self._tracker.is_done("hmi"):
            raise StepAlreadyDoneError("HMI is already set up")
        self._run(compose_command(self._ems_dir, "up", "-d", HMI_SERVICE))
        wait_for_log(self._run, self._ems_dir, HMI_SERVICE, READY_LINE)
        checks = [self._serves_app()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("hmi")
        return StepResult(verified=verified, checks=checks)

    def _serves_app(self) -> VerifyCheck:
        out = self._run(
            Command(
                args=[
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    DOCKER_NETWORK,
                    PROBE_IMAGE,
                    "-fsS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    HMI_URL,
                ]
            )
        )
        ok = out.returncode == 0 and out.stdout.strip() == "200"
        return VerifyCheck(
            name="Serves the operator screen",
            ok=ok,
            detail=(
                "HTTP 200 on port 80"
                if ok
                else f"got {out.stdout.strip() or f'exit {out.returncode}'}"
            ),
            hint=LOG_HINT,
        )
