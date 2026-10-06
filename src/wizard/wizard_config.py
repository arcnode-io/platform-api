"""Loads the wizard's cfg.yml — written by whichever provisioning path set
up the box (setup.sh on-prem, EC2 UserData in the cloud)."""

from pathlib import Path

import yaml

from src.wizard.wizard_record import WizardConfig


def load_wizard_config(path: Path) -> WizardConfig:
    """Parse + validate the wizard config; a missing/bad file fails loudly."""
    return WizardConfig.model_validate(yaml.safe_load(path.read_text()))
