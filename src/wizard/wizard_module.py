"""Wizard module — DI assembly for the standalone setup-wizard app."""

from pathlib import Path

from src.wizard.ssh_verify import Probe
from src.wizard.wizard_controller import WizardController
from src.wizard.wizard_record import Deployment, SshAccount
from src.wizard.wizard_service import WizardService


class WizardModule:
    """Single point of DI for the wizard feature.

    ``base_dir`` is ``/etc/arcnode`` in production (injectable for tests);
    ``account`` is whose authorized_keys the SSH key goes into;
    ``deployment`` comes from wizard-cfg.yml; ``run_probe`` runs the SSH
    verification commands (a fake in tests).
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        account: SshAccount,
        deployment: Deployment,
        run_probe: Probe,
    ) -> None:
        self.service = WizardService(
            account=account,
            deployment=deployment,
            applied_marker_path=base_dir / ".wizard-applied",
            run_probe=run_probe,
        )
        self.router = WizardController(service=self.service).router
