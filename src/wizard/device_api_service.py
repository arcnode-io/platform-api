"""The on-prem Device API page: save the auth secrets the customer sets,
start the Device API with the order's topology, wait until it reaches the
broker, verify. The topology file was copied in by the Site page."""

from pathlib import Path
from typing import Final

from src.customer_inputs import OPERATOR_LOGIN, VIEWER_LOGIN
from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.device_api_verify import DEVICE_API_SERVICE, verify_device_api
from src.wizard.secrets_env import save_secrets
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Deployment, DeviceApiSecrets, StepResult
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

# Same name the cloud's UserData logs once the Device API is on the broker.
CONNECTED_LINE: Final[str] = "mqtt connected"


class DeviceApiStepNotAvailableError(Exception):
    """No Device API page in the cloud — UserData starts it there."""


class DeviceApiService:
    """Starts the Device API that serves the topology and checks operator logins."""

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

    def apply(self, request: DeviceApiSecrets) -> StepResult:
        """Save the secrets, start, wait for the broker, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise DeviceApiStepNotAvailableError("no Device API page in the cloud")
        if self._tracker.is_done("device_api"):
            raise StepAlreadyDoneError("Device API is already set up")
        # Reason: compose reads the env file itself, so the secrets go in before `up`.
        save_secrets(
            self._secrets_env_path,
            {
                "AUTH_JWT_SECRET": request.jwt_secret,
                OPERATOR_LOGIN.env_name: request.operator_password,
                VIEWER_LOGIN.env_name: request.viewer_password,
            },
        )
        self._run(compose_command(self._ems_dir, "up", "-d", DEVICE_API_SERVICE))
        wait_for_log(self._run, self._ems_dir, DEVICE_API_SERVICE, CONNECTED_LINE)
        checks = verify_device_api(
            self._run, request, self._secrets_env_path, self._ems_dir
        )
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("device_api")
        return StepResult(verified=verified, checks=checks)
