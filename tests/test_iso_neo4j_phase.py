"""Integration test: the real install-time phases (docker.sh, then
neo4j.sh) on a real Debian 13 container with a real dockerd, then the real
Docker page and the real Neo4j page, in dependency order — Neo4j moves onto
the gateway Docker actually picked, its default password is changed, and a
real container on that network logs in.

Only `systemctl` is stood in for (containers have no systemd):
restart/is-active map to the neo4j CLI run as the neo4j user, is-active
docker to `docker info`.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from testcontainers.core.container import DockerContainer

from src.wizard.docker_service import DockerService
from src.wizard.neo4j_service import Neo4jService
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    CommandOutput,
    Deployment,
    PasswordRequest,
)
from src.wizard.wizard_steps import StepTracker

PHASES: Final[Path] = Path(__file__).parent.parent / "src" / "iso" / "phases"
PASSWORD: Final[str] = "Ne-4j'pass 1!"
# Readiness gate, not a guessed timeout: wait for the socket to answer,
# and fail fast the moment dockerd itself is gone.
WAIT_FOR_DOCKERD: Final[str] = (
    "until docker info >/dev/null 2>&1; do "
    "pidof dockerd >/dev/null || { tail -20 /tmp/dockerd.log; exit 1; }; "
    "sleep 0.2; done"
)
AS_NEO4J: Final[list[str]] = ["runuser", "-u", "neo4j", "--", "neo4j"]
SYSTEMCTL: Final[dict[tuple[str, str], list[str]]] = {
    ("enable", "neo4j"): ["true"],
    ("restart", "neo4j"): [*AS_NEO4J, "restart"],
    ("is-active", "neo4j"): [*AS_NEO4J, "status"],
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


def _exec(container: DockerContainer, script: str) -> str:
    code, output = container.get_wrapped_container().exec_run(
        ["sh", "-c", script], environment={"DEBIAN_FRONTEND": "noninteractive"}
    )
    assert code == 0, output.decode()[-3000:]
    return output.decode()


@pytest.fixture(scope="module")
def installed() -> Iterator[DockerContainer]:
    """Debian 13 with both real phases applied and dockerd up; Neo4j is
    installed but off, as the install leaves it."""
    # Reason: privileged to run dockerd at all; /var/lib/docker on tmpfs
    # because overlayfs can't stack on the outer container's overlayfs.
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_kwargs(privileged=True, tmpfs={"/var/lib/docker": ""})
    )
    container.start()
    try:
        # iproute2 (ss) ships with every real Debian install, not this image.
        _exec(container, "apt-get update -qq && apt-get install -y -qq iproute2")
        _exec(container, (PHASES / "docker.sh").read_text())
        _exec(container, (PHASES / "neo4j.sh").read_text())
        container.get_wrapped_container().exec_run(
            ["sh", "-c", "dockerd >/tmp/dockerd.log 2>&1"], detach=True
        )
        _exec(container, WAIT_FOR_DOCKERD)
        yield container
    finally:
        container.stop()


def test_install_leaves_neo4j_off_and_held(installed: DockerContainer) -> None:
    # Act
    wants = _exec(installed, "ls /etc/systemd/system/multi-user.target.wants/")
    held = _exec(installed, "apt-mark showhold")

    # Assert: no default-password Neo4j on first boot; no surprise upgrade
    assert "neo4j" not in wants
    assert held.split() == ["neo4j"]


def test_real_neo4j_on_dockers_gateway_passes_every_check(
    installed: DockerContainer, tmp_path: Path
) -> None:
    # Arrange: the Docker page first — it creates the network Neo4j listens on
    run = _container_runner(installed)
    tracker = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM)
    docker_page = DockerService(deployment=Deployment.ON_PREM, tracker=tracker, run=run)
    assert docker_page.apply().verified
    service = Neo4jService(
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
