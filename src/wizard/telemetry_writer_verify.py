"""Playbook-style checks for the Telemetry writer page."""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command
from src.wizard.secrets_env import read_secret
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import VerifyCheck

TELEMETRY_SERVICE: Final[str] = "telemetry-writer"
# The writer logs this once it is subscribed to every measurement topic.
SUBSCRIBED_LINE: Final[str] = "reason_code=Success"
TIMESERIES_URL: Final[str] = "TIMESERIES_URL"
LOG_HINT: Final[str] = f"sudo docker compose -f /opt/arcnode/docker-compose.yaml logs {TELEMETRY_SERVICE}"


def verify_telemetry(run: Runner, secrets_env_path: Path, ems_dir: Path) -> list[VerifyCheck]:
    """Running → subscribed to the broker → the database URL it writes to is saved."""
    return [
        _running(run, ems_dir),
        _subscribed(run, ems_dir),
        _timeseries_saved(secrets_env_path),
    ]


def _running(run: Runner, ems_dir: Path) -> VerifyCheck:
    out = run(compose_command(ems_dir, "ps", "-q", "--status", "running", TELEMETRY_SERVICE))
    running = bool(out.stdout.strip())
    return VerifyCheck(
        name="Telemetry writer running",
        ok=running,
        detail="running" if running else (out.stdout.strip() or f"exit {out.returncode}"),
        hint=LOG_HINT,
    )


def _subscribed(run: Runner, ems_dir: Path) -> VerifyCheck:
    logs = run(compose_command(ems_dir, "logs", TELEMETRY_SERVICE)).stdout
    subscribed = SUBSCRIBED_LINE in logs
    return VerifyCheck(
        name="Subscribed to the measurements",
        ok=subscribed,
        detail="subscribed (reason_code=Success)" if subscribed else "no subscription in the log yet",
        hint=LOG_HINT,
    )


def _timeseries_saved(secrets_env_path: Path) -> VerifyCheck:
    saved = read_secret(secrets_env_path, TIMESERIES_URL) is not None
    return VerifyCheck(
        name="Timeseries database saved",
        ok=saved,
        detail=f"{TIMESERIES_URL} in {secrets_env_path}" if saved else f"{TIMESERIES_URL} missing — finish the PostgreSQL page",
        hint=f"sudo cut -d= -f1 {secrets_env_path}",
    )
