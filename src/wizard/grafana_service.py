"""The on-prem Grafana page: the admin password the customer sets goes into
secrets.env (Grafana reads it from there, as in the cloud); start Grafana,
wait for its listen line, verify the admin login works."""

from pathlib import Path
from typing import Final

from src.customer_inputs import GRAFANA_ADMIN
from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.secrets_env import save_secrets, saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    Deployment,
    PasswordRequest,
    StepResult,
    VerifyCheck,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

GRAFANA_SERVICE: Final[str] = "grafana"
# Grafana's own variable, read from the env file; the cloud sets the same name.
# Reason: an env var name, not a secret value.
PASSWORD_NAME: Final[str] = GRAFANA_ADMIN.env_name
GRAFANA_DATA_DIR: Final[str] = "observability/grafana-data"
LISTEN_LINE: Final[str] = "HTTP Server Listen"
PROBE_IMAGE: Final[str] = "curlimages/curl"
GRAFANA_URL: Final[str] = "http://grafana:3000"
LOG_HINT: Final[str] = (
    "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs grafana"
)


class GrafanaStepNotAvailableError(Exception):
    """No Grafana page in the cloud — UserData starts it there."""


class GrafanaService:
    """Starts the dashboards, behind the admin password the customer set."""

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

    def apply(self, request: PasswordRequest) -> StepResult:
        """Save the password, start, wait for listen, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise GrafanaStepNotAvailableError("no Grafana page in the cloud")
        if self._tracker.is_done("grafana"):
            raise StepAlreadyDoneError("Grafana is already set up")
        # Reason: compose reads the env file itself, so the password goes in before `up`.
        save_secrets(self._secrets_env_path, {PASSWORD_NAME: request.password})
        # Reason: the image runs as uid 472; a root-owned data dir fails Grafana at startup.
        (self._ems_dir / GRAFANA_DATA_DIR).mkdir(parents=True, exist_ok=True)
        self._run(
            Command(
                args=["chown", "-R", "472:472", str(self._ems_dir / GRAFANA_DATA_DIR)]
            )
        )
        self._run(compose_command(self._ems_dir, "up", "-d", GRAFANA_SERVICE))
        wait_for_log(self._run, self._ems_dir, GRAFANA_SERVICE, LISTEN_LINE)
        checks = [self._health(), self._admin_login(request.password), self._saved()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("grafana")
        return StepResult(verified=verified, checks=checks)

    def _health(self) -> VerifyCheck:
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
                    f"{GRAFANA_URL}/api/health",
                ]
            )
        )
        ok = out.returncode == 0 and '"database":"ok"' in out.stdout.replace(" ", "")
        return VerifyCheck(
            name="Grafana answers",
            ok=ok,
            detail=(
                "database ok"
                if ok
                else (out.stdout.strip() or f"exit {out.returncode}")
            ),
            hint=LOG_HINT,
        )

    def _admin_login(self, password: str) -> VerifyCheck:
        # Reason: the password goes in through the environment, expanded by the
        # probe's shell — never in argv.
        out = self._run(
            Command(
                args=[
                    "docker",
                    "run",
                    "--rm",
                    "-e",
                    "GF_PW",
                    "--network",
                    DOCKER_NETWORK,
                    "--entrypoint",
                    "sh",
                    PROBE_IMAGE,
                    "-c",
                    f'curl -fsS -o /dev/null -w "%{{http_code}}" -u "admin:$GF_PW" {GRAFANA_URL}/api/user',
                ],
                env={"GF_PW": password},
            )
        )
        ok = out.returncode == 0 and out.stdout.strip() == "200"
        return VerifyCheck(
            name="Admin login works",
            ok=ok,
            detail=(
                "admin signed in"
                if ok
                else "login refused — check the password you set"
            ),
            hint=LOG_HINT,
        )

    def _saved(self) -> VerifyCheck:
        return saved_check(self._secrets_env_path, [PASSWORD_NAME])
