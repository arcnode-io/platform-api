"""The on-prem Industrial gateway page: start the gateway that turns device
telemetry into broker messages, wait until it has its spec and its
subscriptions, verify. Nothing to type; its site ID came from the Site page."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.secrets_env import saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

GATEWAY_SERVICE: Final[str] = "industrial-gateway"
# The gateway logs these, in order, once it has the topology and is subscribed.
SUBSCRIBED_LINE: Final[str] = "MQTT subscriptions established"
SPEC_LINE: Final[str] = "initial spec fetched"
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs industrial-gateway"


class IndustrialGatewayStepNotAvailableError(Exception):
    """No Industrial gateway page in the cloud — UserData starts it there."""


class IndustrialGatewayService:
    """Starts the gateway that bridges the devices onto the broker."""

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

    def apply(self) -> StepResult:
        """Start, wait for its subscriptions, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise IndustrialGatewayStepNotAvailableError("no Industrial gateway page in the cloud")
        if self._tracker.is_done("industrial_gateway"):
            raise StepAlreadyDoneError("Industrial gateway is already set up")
        self._run(compose_command(self._ems_dir, "up", "-d", GATEWAY_SERVICE))
        wait_for_log(self._run, self._ems_dir, GATEWAY_SERVICE, SUBSCRIBED_LINE)
        checks = self._checks()
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("industrial_gateway")
        return StepResult(verified=verified, checks=checks)

    def _checks(self) -> list[VerifyCheck]:
        running = self._run(compose_command(self._ems_dir, "ps", "-q", "--status", "running", GATEWAY_SERVICE))
        logs = self._run(compose_command(self._ems_dir, "logs", GATEWAY_SERVICE)).stdout
        return [
            VerifyCheck(
                name="Industrial gateway running",
                ok=bool(running.stdout.strip()),
                detail="running" if running.stdout.strip() else "not running",
                hint=LOG_HINT,
            ),
            VerifyCheck(
                name="Loaded the device spec",
                ok=SPEC_LINE in logs,
                detail="spec fetched from the Device API" if SPEC_LINE in logs else "no spec in the log",
                hint=LOG_HINT,
            ),
            VerifyCheck(
                name="Subscribed to the broker",
                ok=SUBSCRIBED_LINE in logs,
                detail="subscriptions established" if SUBSCRIBED_LINE in logs else "no subscriptions in the log",
                hint=LOG_HINT,
            ),
        ]
