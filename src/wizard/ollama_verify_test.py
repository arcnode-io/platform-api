"""Unit tests for the Ollama page's verification rows — each failure mode
blocks, with a console command that debugs it."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from src.wizard.ollama_fixtures import PRODUCTION
from src.wizard.ollama_verify import verify_ollama
from src.wizard.wizard_fixtures import FakeRunner, ok
from src.wizard.wizard_record import (
    DockerNetwork,
    HardwareMinimums,
    OllamaSettings,
    WizardConfig,
)

NETWORK = DockerNetwork(
    subnet=IPv4Network("172.23.0.0/16"), gateway=IPv4Address("172.23.0.1")
)
# What test-mode.sh leaves: no GPU required, tiny models, 8k chat context.
TEST_BOX = PRODUCTION.model_copy(
    update={
        "hardware": HardwareMinimums(
            vcpus=4,
            memory_gib=16,
            gpus=0,
            gpu_memory_gb=0,
            disk_gb=100,
            disk_nvme=False,
        ),
        "ollama": OllamaSettings(
            chat_model="qwen3:0.6b",
            embedding_model="qwen3-embedding:0.6b",
            context_length=8192,
        ),
    }
)


def _rows(
    runner: FakeRunner, tmp_path: Path, config: WizardConfig = PRODUCTION
) -> dict[str, tuple[bool, str]]:
    checks = verify_ollama(runner, config, NETWORK, tmp_path / "analyst.yml")
    return {check.name: (check.ok, check.detail) for check in checks}


def test_a_model_spilling_off_the_gpu_blocks(tmp_path: Path) -> None:
    # Arrange: chat model only 80% in VRAM — slow, and a sign the card is too small
    runner = FakeRunner()
    runner.queries["/api/ps"] = ok(
        '{"models":[{"name":"gemma4:26b","size":25000000000,"size_vram":20000000000,'
        '"context_length":131072}]}'
    )

    # Act
    actual = _rows(runner, tmp_path)["Chat model loaded"]

    # Assert
    assert actual == (False, "gemma4:26b, 80% GPU, context 131072 (need 131072)")


def test_cpu_is_fine_when_the_config_needs_no_gpu(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["/api/ps"] = ok(
        '{"models":[{"name":"qwen3:0.6b","size":900000000,"size_vram":0,'
        '"context_length":8192}]}'
    )

    # Act
    actual = _rows(runner, tmp_path, TEST_BOX)["Chat model loaded"]

    # Assert
    assert actual == (True, "qwen3:0.6b, CPU, context 8192 (need 8192)")


def test_listening_beyond_the_gateway_blocks(tmp_path: Path) -> None:
    # Arrange: OLLAMA_HOST=0.0.0.0 — every LAN host could use the models
    runner = FakeRunner()
    runner.queries["sport = :11434"] = ok("LISTEN 0 4096 0.0.0.0:11434 0.0.0.0:*\n")

    # Act
    actual = _rows(runner, tmp_path)["Listens on Docker's gateway only"]

    # Assert
    assert actual == (False, "0.0.0.0:11434")


def test_ollama_down_shows_curls_error_not_a_crash(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["/api/tags"] = ok(
        "curl: (7) Failed to connect to 172.23.0.1 port 11434\n"
    )

    # Act
    actual = _rows(runner, tmp_path)["Models downloaded"]

    # Assert
    assert actual == (False, "missing: gemma4:26b, qwen3-embedding:4b-ctx8192")
