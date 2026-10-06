"""Unit tests for the wizard's cfg.yml loader."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.wizard.wizard_config import load_wizard_config
from src.wizard.wizard_record import Deployment, WizardConfig


def test_load_reads_the_deployment(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "wizard-cfg.yml"
    path.write_text("deployment: on-prem\n")

    # Act
    actual = load_wizard_config(path)

    # Assert
    assert actual == WizardConfig(deployment=Deployment.ON_PREM)


def test_load_rejects_an_unknown_deployment(tmp_path: Path) -> None:
    # Arrange: a typo must stop the wizard, not quietly pick a behavior
    path = tmp_path / "wizard-cfg.yml"
    path.write_text("deployment: air-gapped\n")

    # Act / Assert
    with pytest.raises(ValidationError):
        load_wizard_config(path)
