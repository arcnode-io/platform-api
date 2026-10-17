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
# file the only on-prem difference from the cloud compose. The HMI is published
# on port 80 here because on-prem has no https-ingress: it's http://<box>/.
ONPREM_OVERRIDE: Final[str] = """networks:
  default:
    name: arcnode
    external: true
services:
  hmi:
    ports:
      - "80:80"
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


# Poll interval for the readiness gate below — not a timeout.
POLL_SECONDS: Final[float] = 0.5


def wait_for_log(run: Runner, ems_dir: Path, service: str, line: str) -> bool:
    """Readiness gate: poll the service's logs until `line` appears. Returns
    False once the container has exited, so a crash ends the wait.
    Reason: these images have no healthcheck, so the log line is the event."""
    while line not in run(compose_command(ems_dir, "logs", service)).stdout:
        if not container_alive(run, ems_dir, service):
            return False
        time.sleep(POLL_SECONDS)
    return True


# Docker's own states: a restart in progress is alive, only an exit is the end.
ALIVE_STATES: Final[tuple[str, ...]] = ("created", "running", "restarting")


def container_alive(run: Runner, ems_dir: Path, service: str) -> bool:
    """Whether the service's container is up or coming back up.
    Reason: `ps --status running` is empty for the moment a restart takes, which read
    as a crash and let a page run its checks before the container was ready."""
    containers = run(compose_command(ems_dir, "ps", "-q", "-a", service)).stdout.split()
    if not containers:
        return False
    state = run(
        Command(
            args=["docker", "inspect", "--format", "{{.State.Status}}", containers[0]]
        )
    )
    return state.stdout.strip() in ALIVE_STATES
