"""Unit tests for the wizard's cfg.yml loader."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.wizard.wizard_config import load_wizard_config
from src.wizard.wizard_record import Deployment, HardwareMinimums, WizardConfig


def test_load_reads_the_deployment(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "wizard-cfg.yml"
    path.write_text(
        "deployment: on-prem\n"
        "hardware:\n"
        "  vcpus: 8\n"
        "  memory_gib: 64\n"
        "  gpus: 1\n"
        "  gpu_memory_gb: 48\n"
        "  disk_gb: 1000\n"
        "  disk_nvme: true\n"
    )

    # Act
    actual = load_wizard_config(path)

    # Assert
    assert actual == WizardConfig(
        deployment=Deployment.ON_PREM,
        hardware=HardwareMinimums(
            vcpus=8,
            memory_gib=64,
            gpus=1,
            gpu_memory_gb=48,
            disk_gb=1000,
            disk_nvme=True,
        ),
    )


def test_load_rejects_an_unknown_deployment(tmp_path: Path) -> None:
    # Arrange: a typo must stop the wizard, not quietly pick a behavior
    path = tmp_path / "wizard-cfg.yml"
    path.write_text("deployment: air-gapped\n")

    # Act / Assert
    with pytest.raises(ValidationError):
        load_wizard_config(path)
