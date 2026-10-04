"""Wizard module — DI assembly for the standalone setup-wizard app."""

from pathlib import Path

from src.wizard.wizard_controller import WizardController
from src.wizard.wizard_service import WizardService


class WizardModule:
    """Single point of DI for the wizard feature.

    All paths point under one base dir (``/etc/arcnode`` in production,
    injectable for tests) — matches this appliance's established
    convention (secrets.env, cfg.customer.yml, etc. all live there).
    """

    def __init__(self, *, base_dir: Path) -> None:
        self.service = WizardService(
            secrets_env_path=base_dir / "secrets.env",
            tls_cert_path=base_dir / "tls" / "cert.pem",
            tls_key_path=base_dir / "tls" / "key.pem",
            applied_marker_path=base_dir / ".wizard-applied",
        )
        self.router = WizardController(
            service=self.service,
            install_identity_path=base_dir / "install.json",
        ).router
