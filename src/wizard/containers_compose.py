"""On-prem compose: the cloud's docker-compose.yaml, fetched from the same
arcnode-public path, plus an override that joins every service to Docker's
arcnode network. The network is what lets the containers reach the host's
Postgres and Neo4j at the gateway address the daemon pages saved."""

import time
from pathlib import Path
from typing import Final

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command

COMPOSE_FILE: Final[str] = "docker-compose.yaml"
ONPREM_OVERRIDE_FILE: Final[str] = "docker-compose.onprem.yaml"
# Reason: compose's default network can't reach the host daemons on the
# arcnode bridge's gateway. Replacing `default` (not per-service) keeps this
# file the only on-prem difference from the cloud compose.
ONPREM_OVERRIDE: Final[str] = """networks:
  default:
    name: arcnode
    external: true
"""


def compose_command(ems_dir: Path, *args: str) -> Command:
    """`docker compose` with the cloud compose + the on-prem override, run
    against /opt/arcnode's env files (the containers' own config.env and
    secrets.env, which compose reads itself)."""
    return Command(
        args=[
            "docker",
            "compose",
            "-f",
            str(ems_dir / COMPOSE_FILE),
            "-f",
            str(ems_dir / ONPREM_OVERRIDE_FILE),
            *args,
        ]
    )


def cloud_compose_command(ems_dir: Path, *args: str) -> Command:
    """`docker compose` with only the cloud compose file. The on-prem override
    joins containers to a pre-made arcnode network, which the cloud box doesn't have."""
    return Command(args=["docker", "compose", "-f", str(ems_dir / COMPOSE_FILE), *args])


# Poll interval for the readiness gate below — not a timeout.
POLL_SECONDS: Final[float] = 0.5


def wait_for_log(run: Runner, ems_dir: Path, service: str, line: str) -> bool:
    """Readiness gate: poll the service's logs until `line` appears. Returns
    False as soon as the container stops running, so a crash ends the wait.
    Reason: these images have no healthcheck, so the log line is the event."""
    while line not in run(compose_command(ems_dir, "logs", service)).stdout:
        running = run(
            compose_command(ems_dir, "ps", "-q", "--status", "running", service)
        )
        if not running.stdout.strip():
            return False
        time.sleep(POLL_SECONDS)
    return True
