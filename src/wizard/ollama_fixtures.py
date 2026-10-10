"""Test fixtures for the Ollama page — imported explicitly by its
*_test.py files (no conftest)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from src.wizard.ollama_service import OllamaService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import (
    Command,
    Deployment,
    HardwareMinimums,
    OllamaSettings,
    WizardConfig,
)

# What setup.sh writes into wizard-cfg.yml.
PRODUCTION: Final[WizardConfig] = WizardConfig(
    deployment=Deployment.ON_PREM,
    hardware=HardwareMinimums(
        vcpus=8, memory_gib=64, gpus=1, gpu_memory_gb=48, disk_gb=1000, disk_nvme=True
    ),
    ollama=OllamaSettings(
        chat_model="gemma4:26b",
        embedding_model="qwen3-embedding:4b",
        context_length=131072,
    ),
)


def pull_lines(total: int = 2000) -> list[str]:
    """A real-shaped /api/pull NDJSON stream for one model."""
    return [
        '{"status":"pulling manifest"}',
        f'{{"status":"pulling 7c3b0f","digest":"sha256:7c3b0f","total":{total},"completed":{total // 2}}}',
        f'{{"status":"pulling 7c3b0f","digest":"sha256:7c3b0f","total":{total},"completed":{total}}}',
        '{"status":"verifying sha256 digest"}',
        '{"status":"writing manifest"}',
        '{"status":"success"}',
    ]


class FakeStream:
    """Stands in for curl's streaming /api/pull: the same lines for every
    model unless a test sets ``by_model``. ``calls`` records each command."""

    def __init__(self) -> None:
        self.calls: list[Command] = []
        self.lines: list[str] = pull_lines()
        self.by_model: dict[str, list[str]] = {}

    def __call__(self, command: Command) -> Iterator[str]:
        """The canned stream for this pull."""
        self.calls.append(command)
        body = command.args[command.args.index("-d") + 1]
        for model, lines in self.by_model.items():
            if f'"{model}"' in body:
                return iter(lines)
        return iter(self.lines)


def make_ollama_service(
    tmp_path: Path,
    config: WizardConfig = PRODUCTION,
    runner: FakeRunner | None = None,
    stream: FakeStream | None = None,
) -> OllamaService:
    """An OllamaService on tmp_path with a healthy (or given) runner + stream."""
    return OllamaService(
        config=config,
        tracker=tracker(tmp_path, config.deployment),
        analyst_cfg_path=tmp_path / "analyst-cfg.customer.yml",
        run=runner or FakeRunner(),
        stream=stream or FakeStream(),
    )
