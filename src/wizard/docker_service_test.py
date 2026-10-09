"""Unit tests for the Docker page — the gate and the network it creates."""

from pathlib import Path

import pytest

from src.wizard.docker_service import DockerService, DockerStepNotAvailableError
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import Command, CommandOutput, Deployment
from src.wizard.wizard_steps import StepAlreadyDoneError


class FreshDocker(FakeRunner):
    """Docker before the wizard ran: no arcnode network until it's created."""

    def __init__(self) -> None:
        super().__init__()
        self.queries["network inspect"] = CommandOutput(
            returncode=1,
            stdout="Error response from daemon: network arcnode not found\n",
        )

    def __call__(self, command: Command) -> CommandOutput:
        """Like FakeRunner, but `network create` makes inspect succeed."""
        output = super().__call__(command)
        if "create" in command.args:
            self.queries["network inspect"] = ok("172.23.0.0/16 172.23.0.1\n")
        return output


def _service(
    tmp_path: Path, runner: FakeRunner, deployment: Deployment = Deployment.ON_PREM
) -> DockerService:
    return DockerService(
        deployment=deployment, tracker=tracker(tmp_path, deployment), run=runner
    )


def test_creates_the_network_and_lets_docker_pick_the_range(tmp_path: Path) -> None:
    # Arrange
    runner = FreshDocker()

    # Act
    actual = _service(tmp_path, runner).apply()

    # Assert: no --subnet — the range is Docker's call
    creates = [c.args for c in runner.calls if "create" in c.args]
    assert creates == [["docker", "network", "create", "arcnode"]]
    assert actual.verified is True
    assert "docker" in tracker(tmp_path).completed()


def test_a_retry_reuses_the_existing_network(tmp_path: Path) -> None:
    # Arrange: network already there (an earlier attempt made it)
    runner = FakeRunner()

    # Act
    _service(tmp_path, runner).apply()

    # Assert: recreating it would change the range Postgres trusts
    assert not [c for c in runner.calls if "create" in c.args]


def test_a_failed_check_keeps_the_page_open(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["run --rm"] = CommandOutput(returncode=125, stdout="pull failed\n")

    # Act
    actual = _service(tmp_path, runner).apply()

    # Assert
    assert actual.verified is False
    assert "docker" not in tracker(tmp_path).completed()


def test_done_page_refuses_a_redo(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeRunner())
    service.apply()

    # Act / Assert
    with pytest.raises(StepAlreadyDoneError):
        service.apply()


def test_no_docker_page_in_the_cloud(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeRunner(), Deployment.CLOUD)

    # Act / Assert
    with pytest.raises(DockerStepNotAvailableError):
        service.apply()
