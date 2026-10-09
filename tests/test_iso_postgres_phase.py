"""Integration test: the real install-time phases (docker.sh, then
postgres.sh) on a real Debian 13 container with a real dockerd, then the
real Docker page and the real PostgreSQL page, in dependency order —
Postgres trusts the range Docker actually picked, and a real container on
that network connects with the password.

Only `systemctl` is stood in for (containers have no systemd):
is-active/restart map to `pg_ctlcluster` for Postgres and `docker info`
for Docker.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from testcontainers.core.container import DockerContainer

from src.wizard.docker_service import DockerService
from src.wizard.postgres_service import PostgresService
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    CommandOutput,
    Deployment,
    PasswordRequest,
)
from src.wizard.wizard_steps import StepTracker

PHASES: Final[Path] = Path(__file__).parent.parent / "src" / "iso" / "phases"
PASSWORD: Final[str] = "Pg-pass'1 ok"
# Readiness gate, not a guessed timeout: wait for the socket to answer,
# and fail fast the moment dockerd itself is gone.
WAIT_FOR_DOCKERD: Final[str] = (
    "until docker info >/dev/null 2>&1; do "
    "pidof dockerd >/dev/null || { tail -20 /tmp/dockerd.log; exit 1; }; "
    "sleep 0.2; done"
)
SYSTEMCTL: Final[dict[tuple[str, str], list[str]]] = {
    ("is-active", "postgresql@17-main"): ["pg_ctlcluster", "17", "main", "status"],
    ("restart", "postgresql@17-main"): ["pg_ctlcluster", "17", "main", "restart"],
    ("is-active", "docker"): ["docker", "info"],
}


def _container_runner(container: DockerContainer) -> Runner:
    """Run each wizard Command inside the container, stdin/env intact."""
    docker = container.get_wrapped_container()

    def run(command: Command) -> CommandOutput:
        args = command.args
        if args[0] == "systemctl":
            code, _ = docker.exec_run(SYSTEMCTL[(args[1], args[2])])
            state = "active\n" if code == 0 else "inactive\n"
            return CommandOutput(returncode=code, stdout=state)
        env = dict(command.env)
        if command.input is not None:
            env["ARCNODE_STDIN"] = command.input
            args = ["sh", "-c", 'printf "%s" "$ARCNODE_STDIN" | "$@"', "sh", *args]
        code, output = docker.exec_run(args, environment=env)
        return CommandOutput(returncode=code, stdout=output.decode())

    return run


def _exec(container: DockerContainer, script: str) -> None:
    code, output = container.get_wrapped_container().exec_run(
        ["sh", "-c", script], environment={"DEBIAN_FRONTEND": "noninteractive"}
    )
    assert code == 0, output.decode()[-3000:]


@pytest.fixture(scope="module")
def installed() -> Iterator[DockerContainer]:
    """Debian 13 with both real phases applied, dockerd + Postgres up."""
    # Reason: privileged to run dockerd at all; /var/lib/docker on tmpfs
    # because overlayfs can't stack on the outer container's overlayfs.
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_kwargs(privileged=True, tmpfs={"/var/lib/docker": ""})
    )
    container.start()
    try:
        _exec(container, "apt-get update -qq")
        _exec(container, (PHASES / "docker.sh").read_text())
        _exec(container, (PHASES / "postgres.sh").read_text())
        container.get_wrapped_container().exec_run(
            ["sh", "-c", "dockerd >/tmp/dockerd.log 2>&1"], detach=True
        )
        _exec(container, WAIT_FOR_DOCKERD)
        _exec(container, "pg_ctlcluster 17 main start")
        yield container
    finally:
        container.stop()


def test_real_postgres_on_dockers_range_passes_every_check(
    installed: DockerContainer, tmp_path: Path
) -> None:
    # Arrange: the Docker page first — it creates the network Postgres trusts
    run = _container_runner(installed)
    tracker = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM)
    docker_page = DockerService(deployment=Deployment.ON_PREM, tracker=tracker, run=run)
    assert docker_page.apply().verified
    service = PostgresService(
        deployment=Deployment.ON_PREM,
        tracker=tracker,
        secrets_env_path=tmp_path / "secrets.env",
        run=run,
    )

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    actual = {check.name: (check.ok, check.detail) for check in result.checks}
    assert all(ok for ok, _ in actual.values()), actual
    assert result.verified


def test_phase_is_safe_to_rerun(installed: DockerContainer) -> None:
    # Arrange: late_command retries, or a re-provision
    docker = installed.get_wrapped_container()

    # Act
    _exec(installed, (PHASES / "postgres.sh").read_text())
    _, hba = docker.exec_run(
        ["grep", "-c", "include_dir pg_hba.d", "/etc/postgresql/17/main/pg_hba.conf"]
    )

    # Assert: no duplicated include line
    assert hba.decode().strip() == "1"
