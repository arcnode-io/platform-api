"""Unit tests for the wizard's cfg.yml loader."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.wizard.wizard_config import load_wizard_config
from src.wizard.wizard_record import HardwareMinimums, OllamaSettings, WizardConfig


def test_load_reads_the_hardware_minimums_and_the_ollama_models(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "wizard-cfg.yml"
    path.write_text(
        "hardware:\n"
        "  vcpus: 8\n"
        "  memory_gib: 64\n"
        "  gpus: 1\n"
        "  gpu_memory_gb: 48\n"
        "  disk_gb: 1000\n"
        "  disk_nvme: true\n"
        "ollama:\n"
        "  chat_model: gemma4:26b\n"
        "  embedding_model: qwen3-embedding:4b\n"
        "  context_length: 131072\n"
    )

    # Act
    actual = load_wizard_config(path)

    # Assert
    assert actual == WizardConfig(
        hardware=HardwareMinimums(
            vcpus=8,
            memory_gib=64,
            gpus=1,
            gpu_memory_gb=48,
            disk_gb=1000,
            disk_nvme=True,
        ),
        ollama=OllamaSettings(
            chat_model="gemma4:26b",
            embedding_model="qwen3-embedding:4b",
            context_length=131072,
        ),
    )


def test_load_rejects_a_config_without_the_ollama_models(tmp_path: Path) -> None:
    # Arrange: a half-written file must stop the wizard, not reach the Ollama page
    path = tmp_path / "wizard-cfg.yml"
    path.write_text(
        "hardware:\n"
        "  vcpus: 8\n"
        "  memory_gib: 64\n"
        "  gpus: 1\n"
        "  gpu_memory_gb: 48\n"
        "  disk_gb: 1000\n"
        "  disk_nvme: true\n"
    )

    # Act / Assert
    with pytest.raises(ValidationError):
        load_wizard_config(path)
