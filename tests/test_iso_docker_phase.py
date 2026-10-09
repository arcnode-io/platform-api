"""Integration test: the real install-time phase (src/iso/phases/docker.sh)
on a real Debian 13 container, a real dockerd inside it, then the real
DockerService — network created by Docker, a real image pulled and run.

Only `systemctl` is stood in for (containers have no systemd): it maps to
`docker info`, which only succeeds against a running daemon.
"""

from collections.abc import Iterator
from ipaddress import IPv4Network
from pathlib import Path
from typing import Final

import pytest
from testcontainers.core.container import DockerContainer

from src.wizard.docker_service import DockerService
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, CommandOutput, Deployment
from src.wizard.wizard_steps import StepTracker

REPO_ROOT: Final[Path] = Path(__file__).parent.parent
PHASE_SCRIPT: Final[str] = (
    REPO_ROOT / "src" / "iso" / "phases" / "docker.sh"
).read_text()
# Readiness gate, not a guessed timeout: wait for the socket to answer,
# and fail fast the moment dockerd itself is gone.
WAIT_FOR_DOCKERD: Final[str] = (
    "until docker info >/dev/null 2>&1; do "
    "pidof dockerd >/dev/null || { tail -20 /tmp/dockerd.log; exit 1; }; "
    "sleep 0.2; done"
)


def _container_runner(container: DockerContainer) -> Runner:
    """Run each wizard Command inside the container."""
    docker = container.get_wrapped_container()

    def run(command: Command) -> CommandOutput:
        if command.args[:2] == ["systemctl", "is-active"]:
            code, _ = docker.exec_run(["docker", "info"])
            return CommandOutput(
                returncode=code, stdout="active\n" if code == 0 else "inactive\n"
            )
        code, output = docker.exec_run(command.args)
        return CommandOutput(returncode=code, stdout=output.decode())

    return run


@pytest.fixture(scope="module")
def installed() -> Iterator[DockerContainer]:
    """Debian 13 with the real docker phase applied and dockerd running."""
    # Reason: privileged to run dockerd at all; /var/lib/docker on tmpfs
    # because overlayfs can't stack on the outer container's overlayfs.
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_kwargs(privileged=True, tmpfs={"/var/lib/docker": ""})
    )
    container.start()
    try:
        docker = container.get_wrapped_container()
        code, output = docker.exec_run(["sh", "-c", "apt-get update -qq"])
        assert code == 0, output.decode()
        code, output = docker.exec_run(
            ["sh", "-c", PHASE_SCRIPT],
            environment={"DEBIAN_FRONTEND": "noninteractive"},
        )
        assert code == 0, output.decode()[-3000:]
        docker.exec_run(["sh", "-c", "dockerd >/tmp/dockerd.log 2>&1"], detach=True)
        code, output = docker.exec_run(["sh", "-c", WAIT_FOR_DOCKERD])
        assert code == 0, output.decode()
        yield container
    finally:
        container.stop()


def _service(container: DockerContainer, tmp_path: Path) -> DockerService:
    return DockerService(
        deployment=Deployment.ON_PREM,
        tracker=StepTracker(
            steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM
        ),
        run=_container_runner(container),
    )


def test_real_docker_passes_every_check(
    installed: DockerContainer, tmp_path: Path
) -> None:
    # Arrange
    service = _service(installed, tmp_path)

    # Act
    actual = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in actual.checks] == [
        ("Docker daemon running", True),
        ("arcnode network", True),
        ("A container joins the network", True),
    ], [c.detail for c in actual.checks]
    assert actual.verified is True


def test_a_retry_keeps_the_range_docker_picked(
    installed: DockerContainer, tmp_path: Path
) -> None:
    # Arrange: the page already ran once (module-scoped container)
    first = _service(installed, tmp_path / "a").apply().checks[1].detail

    # Act
    second = _service(installed, tmp_path / "b").apply().checks[1].detail

    # Assert: same network, same range — Postgres's trust stays valid
    assert second == first
    IPv4Network(first.split(",")[0])  # a real range, as Docker reported it
