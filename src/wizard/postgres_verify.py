"""Playbook-style verification for the PostgreSQL page — each check a row
the UI shows, with the console command that debugs it. The network-facing
rows (listen, pg_hba, a real container) are in postgres_access_verify.py."""

from pathlib import Path
from typing import Final

from src.wizard.postgres_access_verify import verify_access
from src.wizard.secrets_env import saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, DockerNetwork, VerifyCheck

PG_UNIT: Final[str] = (
    "postgresql@17-main"  # the real cluster; postgresql.service is a no-op umbrella
)
PG_LOG_HINT: Final[str] = "sudo tail -n 50 /var/log/postgresql/postgresql-17-main.log"
# Same databases + env var names as the cloud (aurora_bootstrap.SLICE_SPECS,
# cfn_resources.COMMON_URL_SLOTS), so the containers can't tell the difference.
EMS_DATABASES: Final[dict[str, str]] = {
    "DOCUMENT_URL": "ems_document",
    "VECTOR_URL": "ems_vector",
    "TIMESERIES_URL": "ems_timeseries",
    "DER_CONTROL_URL": "ems_dercontrol",
}
# Forced difference from the cloud: Aurora has no TimescaleDB (it uses
# pg_partman); on-prem gets the real thing.
EXTENSION_DATABASES: Final[dict[str, str]] = {
    "timescaledb": "ems_timeseries",
    "vector": "ems_vector",
}
# Literal SQL — nothing interpolated into a query.
EXTENSION_VERSION_SQL: Final[dict[str, str]] = {
    "timescaledb": "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'",
    "vector": "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
}
EMS_DATABASES_SQL: Final[str] = (
    "SELECT datname FROM pg_database WHERE datname LIKE 'ems\\_%'"
)


def psql_as_postgres(sql: str, database: str = "postgres") -> Command:
    """Run one SQL string as the postgres OS user over the local socket."""
    return Command(
        args=["runuser", "-u", "postgres", "--", "psql", "-d", database, "-tAc", sql]
    )


def verify_postgres(
    run: Runner, password: str, network: DockerNetwork, secrets_env_path: Path
) -> list[VerifyCheck]:
    """Running → password → databases → extensions → reachable from Docker
    only → URLs saved for the containers."""
    return [
        _running(run),
        _accepts_password(run, password),
        _databases(run),
        _extension(run, "timescaledb", "TimescaleDB extension"),
        _extension(run, "vector", "pgvector extension"),
        *verify_access(run, password, network),
        saved_check(secrets_env_path, list(EMS_DATABASES)),
    ]


def _running(run: Runner) -> VerifyCheck:
    out = run(Command(args=["systemctl", "is-active", PG_UNIT]))
    state = out.stdout.strip() or f"exit {out.returncode}"
    return VerifyCheck(
        name="PostgreSQL 17 running",
        ok=state == "active",
        detail=state,
        hint=f"sudo systemctl status {PG_UNIT}; {PG_LOG_HINT}",
    )


def _accepts_password(run: Runner, password: str) -> VerifyCheck:
    # Over TCP to 127.0.0.1 so the password is actually checked (the local
    # socket would use peer auth); PGPASSWORD keeps it out of argv.
    out = run(
        Command(
            args=[
                "psql",
                "-h",
                "127.0.0.1",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-tAc",
                "SELECT current_user",
            ],
            env={"PGPASSWORD": password},
        )
    )
    ok = out.returncode == 0 and out.stdout.strip() == "postgres"
    first_line = (out.stdout.strip().splitlines() or [f"exit {out.returncode}"])[0]
    return VerifyCheck(
        name="Accepts the password you set",
        ok=ok,
        detail="connected as postgres" if ok else first_line,
        hint=PG_LOG_HINT,
    )


def _databases(run: Runner) -> VerifyCheck:
    found = set(run(psql_as_postgres(EMS_DATABASES_SQL)).stdout.split())
    missing = [db for db in EMS_DATABASES.values() if db not in found]
    return VerifyCheck(
        name="EMS databases",
        ok=not missing,
        detail=(
            f"missing {', '.join(missing)}"
            if missing
            else ", ".join(EMS_DATABASES.values())
        ),
        hint="sudo -u postgres psql -l",
    )


def _extension(run: Runner, extname: str, name: str) -> VerifyCheck:
    database = EXTENSION_DATABASES[extname]
    out = run(psql_as_postgres(EXTENSION_VERSION_SQL[extname], database))
    version = out.stdout.strip()
    ok = out.returncode == 0 and bool(version)
    return VerifyCheck(
        name=name,
        ok=ok,
        detail=(
            f"{version} in {database}" if ok else f"{extname} not created in {database}"
        ),
        hint=f"sudo -u postgres psql -d {database} -c '\\dx'; "
        "grep shared_preload_libraries /etc/postgresql/17/main/postgresql.conf",
    )
