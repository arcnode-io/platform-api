"""Wizard module — DI assembly for the standalone setup-wizard app."""

from pathlib import Path

from src.wizard.docker_service import DockerService
from src.wizard.neo4j_service import Neo4jService
from src.wizard.postgres_service import PostgresService
from src.wizard.preflight_service import PreflightService
from src.wizard.ssh_service import SshService
from src.wizard.system_runner import Runner
from src.wizard.wizard_controller import WizardController
from src.wizard.wizard_record import SshAccount, WizardConfig
from src.wizard.wizard_steps import StepTracker


class WizardModule:
    """Single point of DI for the wizard feature.

    ``base_dir`` is ``/etc/arcnode`` in production (injectable for tests);
    ``secrets_env_path`` is the env file the EMS containers load (the same
    ``/opt/arcnode/secrets.env`` as the cloud);
    ``account`` is whose authorized_keys the SSH key goes into;
    ``config`` is wizard-cfg.yml (deployment + hardware minimums); ``run`` runs the install and
    verification commands (a fake in tests).
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        secrets_env_path: Path,
        account: SshAccount,
        config: WizardConfig,
        run: Runner,
    ) -> None:
        deployment = config.deployment
        tracker = StepTracker(steps_dir=base_dir / "steps", deployment=deployment)
        self.preflight = PreflightService(
            tracker=tracker,
            minimums=config.hardware,
            run=run,
        )
        self.ssh = SshService(
            account=account, deployment=deployment, tracker=tracker, run=run
        )
        self.docker = DockerService(deployment=deployment, tracker=tracker, run=run)
        self.postgres = PostgresService(
            deployment=deployment,
            tracker=tracker,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.neo4j = Neo4jService(
            deployment=deployment,
            tracker=tracker,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.router = WizardController(
            preflight=self.preflight,
            ssh=self.ssh,
            docker=self.docker,
            postgres=self.postgres,
            neo4j=self.neo4j,
            tracker=tracker,
            deployment=deployment,
            account=account,
        ).router
