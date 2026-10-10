"""The on-prem HiveMQ page: write the broker's account file from the six
passwords the customer sets, save those passwords for the EMS services, start
the broker on the arcnode network, verify every login. Docker was set up by
the Docker page; the compose file is the cloud's, from arcnode-public."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import (
    COMPOSE_FILE,
    COMPOSE_URL,
    ONPREM_OVERRIDE,
    ONPREM_OVERRIDE_FILE,
    compose_command,
    wait_for_log,
)
from src.wizard.hivemq_credentials import render_credentials
from src.wizard.hivemq_verify import ACCOUNTS, HIVEMQ_SERVICE, verify_hivemq
from src.wizard.secrets_env import save_secrets
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    BrokerPasswords,
    Command,
    Deployment,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

# Same template the cloud's UserData fetches and fills with sed.
TEMPLATE_FILE: Final[str] = "credentials.template.xml"
CREDENTIALS_FILE: Final[str] = "credentials.xml"
CONFIG_FILE: Final[str] = "config.env"
# Written empty: the on-prem box has no AWS settings for the containers.
STARTED_LINE: Final[str] = "Started HiveMQ"


class HivemqStepNotAvailableError(Exception):
    """No HiveMQ page in the cloud — UserData starts the broker there."""


class HivemqService:
    """Everything the EMS containers need from the on-prem broker."""

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

    def apply(self, request: BrokerPasswords) -> StepResult:
        """Write the files, start the broker, verify — the page is only marked
        done when every check passes. Every step is idempotent, so a retry is safe."""
        if self._deployment == Deployment.CLOUD:
            raise HivemqStepNotAvailableError("no HiveMQ step in the cloud")
        if self._tracker.is_done("hivemq"):
            raise StepAlreadyDoneError("HiveMQ is already set up")
        self._fetch_files()
        self._write_files(request)
        # Reason: compose reads these env files itself, so they must exist
        # before `up` — the saved passwords come first.
        save_secrets(self._secrets_env_path, self._env_values(request))
        self._run(compose_command(self._ems_dir, "up", "-d", HIVEMQ_SERVICE))
        self._wait_for_started()
        checks = verify_hivemq(
            self._run, request, self._secrets_env_path, self._ems_dir
        )
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("hivemq")
        return StepResult(verified=verified, checks=checks)

    def _fetch_files(self) -> None:
        """The cloud's compose file, from arcnode-public. The credentials template is in the ISO."""
        self._run(
            Command(args=["curl", "-fsSL", COMPOSE_URL, "-o", str(self._ems_dir / COMPOSE_FILE)])
        )

    def _write_files(self, request: BrokerPasswords) -> None:
        """config.env (empty), the broker's credentials.xml (0600), the override."""
        (self._ems_dir / CONFIG_FILE).write_text("")
        template = (self._ems_dir / TEMPLATE_FILE).read_text()
        placeholders = {
            f"{account.upper()}_PASSWORD": getattr(request, password_field)
            for account, _, _, password_field in ACCOUNTS
        }
        credentials = self._ems_dir / CREDENTIALS_FILE
        credentials.touch(mode=0o600)
        credentials.chmod(0o600)
        credentials.write_text(render_credentials(template, placeholders))
        (self._ems_dir / ONPREM_OVERRIDE_FILE).write_text(ONPREM_OVERRIDE)

    def _env_values(self, request: BrokerPasswords) -> dict[str, str]:
        """The six MQTT_*_PASSWORD names the cloud's secrets.env uses."""
        return {env: getattr(request, password_field) for _, _, env, password_field in ACCOUNTS}

    def _wait_for_started(self) -> bool:
        return wait_for_log(self._run, self._ems_dir, HIVEMQ_SERVICE, STARTED_LINE)
