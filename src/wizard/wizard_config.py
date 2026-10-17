"""Loads the wizard's cfg.yml, which setup.sh writes."""

from pathlib import Path

import yaml

from src.wizard.wizard_record import WizardConfig


def load_wizard_config(path: Path) -> WizardConfig:
    """Parse + validate the wizard config; a missing/bad file fails loudly."""
    return WizardConfig.model_validate(yaml.safe_load(path.read_text()))
