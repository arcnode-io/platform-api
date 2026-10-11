"""The cloud password page: save the operator, viewer, and Grafana passwords
the customer sets, the same names the on-prem wizard writes. Cloud only."""

from pathlib import Path

from src.customer_inputs import GRAFANA_ADMIN, OPERATOR_LOGIN, VIEWER_LOGIN
from src.wizard.containers_compose import cloud_compose_command
from src.wizard.secrets_env import save_secrets, saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import CloudSecrets, Deployment, StepResult
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

SAVED_NAMES: list[str] = [
    OPERATOR_LOGIN.env_name,
    VIEWER_LOGIN.env_name,
    GRAFANA_ADMIN.env_name,
]


class CloudSecretsStepNotAvailableError(Exception):
    """The cloud password page only exists in the cloud."""


class CloudSecretsService:
    """Writes the cloud customer's passwords to secrets.env."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        secrets_env_path: Path,
        ems_dir: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._secrets_env_path = secrets_env_path
        self._ems_dir = ems_dir
        self._run = run

    def apply(self, request: CloudSecrets) -> StepResult:
        """Save the passwords, then verify they're on disk — done only when the check passes."""
        if self._deployment != Deployment.CLOUD:
            raise CloudSecretsStepNotAvailableError("no cloud password page on-prem")
        if self._tracker.is_done("cloud_secrets"):
            raise StepAlreadyDoneError("the cloud passwords are already set")
        save_secrets(
            self._secrets_env_path,
            {
                OPERATOR_LOGIN.env_name: request.operator_password,
                VIEWER_LOGIN.env_name: request.viewer_password,
                GRAFANA_ADMIN.env_name: request.grafana_password,
            },
        )
        checks = [saved_check(self._secrets_env_path, SAVED_NAMES)]
        verified = all(check.ok for check in checks)
        if verified:
            # Reason: the containers were held back at boot until these passwords exist.
            self._run(cloud_compose_command(self._ems_dir, "up", "-d"))
            self._tracker.mark_done("cloud_secrets")
        return StepResult(verified=verified, checks=checks)
