"""Unit tests for the Ollama page — progress streams while models download,
the page gates on every check, and nothing is half-prepared on a failed
download."""

from pathlib import Path

import pytest
import yaml

from src.wizard.ollama_fixtures import PRODUCTION, FakeStream, make_ollama_service
from src.wizard.ollama_service import OllamaStepNotAvailableError
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import Deployment


def test_healthy_box_streams_progress_then_a_verified_result(tmp_path: Path) -> None:
    # Arrange
    service = make_ollama_service(tmp_path)

    # Act
    events = list(service.apply())

    # Assert
    progress = [(e.progress.model, e.progress.completed) for e in events if e.progress]
    result = events[-1].result
    assert progress[:3] == [
        ("gemma4:26b", None),
        ("gemma4:26b", 1000),
        ("gemma4:26b", 2000),
    ]
    assert {model for model, _ in progress} == {"gemma4:26b", "qwen3-embedding:4b"}
    assert result is not None
    assert result.verified, [c for c in result.checks if not c.ok]
    assert tracker(tmp_path).is_done("ollama")


def test_writes_the_analyst_cfg_pointing_at_the_gateway(tmp_path: Path) -> None:
    # Arrange
    service = make_ollama_service(tmp_path)
    expected = {
        "settings": {
            "llm_provider": "ollama",
            "ollama_base_url": "http://172.23.0.1:11434/v1",
            "ollama_chat_model": "gemma4:26b",
            "ollama_embedding_model": "qwen3-embedding:4b-ctx8192",
        }
    }

    # Act
    list(service.apply())

    # Assert
    actual = yaml.safe_load((tmp_path / "analyst-cfg.customer.yml").read_text())
    assert actual == expected


def test_drop_in_puts_ollama_on_the_gateway_with_the_configured_context(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_ollama_service(tmp_path, runner=runner)

    # Act
    list(service.apply())

    # Assert
    actual = next(c.input for c in runner.calls if c.args[0] == "tee") or ""
    assert 'Environment="OLLAMA_HOST=172.23.0.1:11434"' in actual
    assert 'Environment="OLLAMA_CONTEXT_LENGTH=131072"' in actual
    assert 'Environment="OLLAMA_KEEP_ALIVE=-1"' in actual


def test_a_failed_download_stops_before_preparing_anything(tmp_path: Path) -> None:
    # Arrange: Ollama reports errors in-band, on an HTTP 200 stream
    runner = FakeRunner()
    stream = FakeStream()
    stream.by_model["gemma4:26b"] = [
        '{"status":"pulling manifest"}',
        '{"error":"pull model manifest: file does not exist"}',
    ]
    service = make_ollama_service(tmp_path, runner=runner, stream=stream)

    # Act
    events = list(service.apply())

    # Assert
    last_progress = [e.progress for e in events if e.progress][-1]
    called = [" ".join(c.args) for c in runner.calls]
    assert last_progress.status == "error: pull model manifest: file does not exist"
    assert len(stream.calls) == 1  # the embedding model isn't attempted
    assert not any("/api/create" in c for c in called)
    assert not (tmp_path / "analyst-cfg.customer.yml").exists()
    assert events[-1].result is not None and not events[-1].result.verified


def test_cloud_has_no_ollama_page(tmp_path: Path) -> None:
    # Arrange
    cloud = PRODUCTION.model_copy(update={"deployment": Deployment.CLOUD})
    service = make_ollama_service(tmp_path, config=cloud)

    # Act / Assert — refused up front, before any stream starts
    with pytest.raises(OllamaStepNotAvailableError):
        service.apply()
