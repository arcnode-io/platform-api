"""The on-prem Docker page: create the arcnode network, verify. Docker
itself was installed at install time by src/iso/phases/docker.sh."""

from src.wizard.docker_verify import DOCKER_NETWORK, inspect_network, verify_docker
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, StepResult
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker


class DockerStepNotAvailableError(Exception):
    """No Docker page in the cloud — EC2 UserData sets Docker up."""


class DockerService:
    """Create the network every EMS container and host daemon meets on."""

    def __init__(
        self, *, deployment: Deployment, tracker: StepTracker, run: Runner
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._run = run

    def apply(self) -> StepResult:
        """Create arcnode if missing, then verify — the page is marked done
        only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise DockerStepNotAvailableError("no Docker step in the cloud")
        if self._tracker.is_done("docker"):
            raise StepAlreadyDoneError("Docker is already set up")
        # Reason: never recreate it — a new network can get a new range, and
        # Postgres's pg_hba trusts the range this one was given.
        if inspect_network(self._run).returncode != 0:
            # No --subnet: Docker picks a free range from its address pools.
            self._run(Command(args=["docker", "network", "create", DOCKER_NETWORK]))
        checks = verify_docker(self._run)
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("docker")
        return StepResult(verified=verified, checks=checks)
