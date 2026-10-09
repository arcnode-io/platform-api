"""The on-prem PostgreSQL page: open Postgres to the range Docker picked,
set the password, create the cloud's four databases, save their URLs for
the EMS containers, verify. Packages + TimescaleDB tuning were done at
install time by src/iso/phases/postgres.sh."""

from pathlib import Path
from typing import Final
from urllib.parse import quote

from src.wizard.docker_verify import missing_network_check, read_network
from src.wizard.postgres_verify import (
    EMS_DATABASES,
    EXTENSION_DATABASES,
    PG_UNIT,
    psql_as_postgres,
    verify_postgres,
)
from src.wizard.secrets_env import save_secrets
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    Deployment,
    DockerNetwork,
    PasswordRequest,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

# Ours alone: Debian's postgresql.conf includes conf.d, and the install
# phase adds `include_dir pg_hba.d` to pg_hba.conf.
LISTEN_CONF: Final[str] = "/etc/postgresql/17/main/conf.d/arcnode.conf"
HBA_RULES: Final[str] = "/etc/postgresql/17/main/pg_hba.d/arcnode.conf"
# CREATE DATABASE has no IF NOT EXISTS; \gexec runs it only when the
# SELECT finds it missing. Literal SQL — one line per EMS_DATABASES entry.
CREATE_DATABASES_SQL: Final[str] = (
    "SELECT 'CREATE DATABASE ems_document' WHERE NOT EXISTS "
    "(SELECT FROM pg_database WHERE datname = 'ems_document')\\gexec\n"
    "SELECT 'CREATE DATABASE ems_vector' WHERE NOT EXISTS "
    "(SELECT FROM pg_database WHERE datname = 'ems_vector')\\gexec\n"
    "SELECT 'CREATE DATABASE ems_timeseries' WHERE NOT EXISTS "
    "(SELECT FROM pg_database WHERE datname = 'ems_timeseries')\\gexec\n"
    "SELECT 'CREATE DATABASE ems_dercontrol' WHERE NOT EXISTS "
    "(SELECT FROM pg_database WHERE datname = 'ems_dercontrol')\\gexec\n"
)
PSQL_SCRIPT: Final[list[str]] = [
    "runuser", "-u", "postgres", "--",
    "psql", "-v", "ON_ERROR_STOP=1", "-q", "-d", "postgres",
]  # fmt: skip


class PostgresStepNotAvailableError(Exception):
    """No PostgreSQL page in the cloud — databases are managed services."""


class PostgresService:
    """Everything the EMS containers need from the host's PostgreSQL."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        secrets_env_path: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._secrets_env_path = secrets_env_path
        self._run = run

    def apply(self, request: PasswordRequest) -> StepResult:
        """Configure, then verify — the page is only marked done when every
        check passes. Every step is idempotent, so a retry is safe."""
        if self._deployment == Deployment.CLOUD:
            raise PostgresStepNotAvailableError("no PostgreSQL step in the cloud")
        if self._tracker.is_done("postgres"):
            raise StepAlreadyDoneError("PostgreSQL is already set up")
        network = read_network(self._run)
        if network is None:
            return StepResult(verified=False, checks=[missing_network_check()])
        self._open_to_docker(network)
        self._set_password(request.password)
        self._create_databases()
        self._save_urls(request.password, network)
        checks = verify_postgres(
            self._run, request.password, network, self._secrets_env_path
        )
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("postgres")
        return StepResult(verified=verified, checks=checks)

    def _open_to_docker(self, network: DockerNetwork) -> None:
        """Listen on the gateway, trust the range — both as Docker reports."""
        self._run(
            Command(
                args=["tee", LISTEN_CONF],
                input=f"listen_addresses = 'localhost,{network.gateway}'\n",
            )
        )
        self._run(
            Command(
                args=["tee", HBA_RULES],
                input=f"host all all {network.subnet} scram-sha-256\n",
            )
        )
        # listen_addresses only changes on a restart, not a reload.
        self._run(Command(args=["systemctl", "restart", PG_UNIT]))

    def _set_password(self, password: str) -> None:
        # Reason: through the environment + \\getenv, not argv (visible in
        # ps) and not spliced into SQL (a ' would break it); :'pw' makes
        # psql quote it as a literal.
        self._run(
            Command(
                args=PSQL_SCRIPT,
                input="\\getenv pw POSTGRES_PASSWORD\nALTER USER postgres PASSWORD :'pw';\n",
                env={"POSTGRES_PASSWORD": password},
            )
        )

    def _create_databases(self) -> None:
        self._run(
            Command(
                args=PSQL_SCRIPT,
                input=CREATE_DATABASES_SQL,
            )
        )
        for extname, database in EXTENSION_DATABASES.items():
            self._run(
                psql_as_postgres(f"CREATE EXTENSION IF NOT EXISTS {extname}", database)
            )

    def _save_urls(self, password: str, network: DockerNetwork) -> None:
        """The cloud's four URLs, pointing at the gateway."""
        # Percent-encoded: the customer's password has special characters.
        host = f"postgres://postgres:{quote(password, safe='')}@{network.gateway}:5432"
        save_secrets(
            self._secrets_env_path,
            {name: f"{host}/{db}" for name, db in EMS_DATABASES.items()},
        )
