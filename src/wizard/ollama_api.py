"""Talking to the host's Ollama: where it listens, the curl commands for
its API, and what the page writes for ems-analyst."""

import json
from typing import Final

from pydantic import BaseModel, ValidationError

from src.wizard.ems_cfg import AnalystCfg, AnalystOllamaSettings
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, DockerNetwork, OllamaSettings

OLLAMA_UNIT: Final[str] = "ollama"
OLLAMA_PORT: Final[int] = 11434
# The embedding model gets its own small context (a variant of the same
# weights) — at the chat's 128k it wouldn't fit next to the chat model.
EMBED_CONTEXT: Final[int] = 8192


def base_url(network: DockerNetwork) -> str:
    """Ollama on the arcnode gateway — the one address it listens on."""
    return f"http://{network.gateway}:{OLLAMA_PORT}"


def embedding_variant(settings: OllamaSettings) -> str:
    """The 8k-context copy of the embedding model the page creates."""
    return f"{settings.embedding_model}-ctx{EMBED_CONTEXT}"


def analyst_cfg(network: DockerNetwork, settings: OllamaSettings) -> AnalystCfg:
    """What the page writes for ems-analyst: Ollama's OpenAI-style API."""
    return AnalystCfg(
        settings=AnalystOllamaSettings(
            ollama_base_url=f"{base_url(network)}/v1",
            ollama_chat_model=settings.chat_model,
            ollama_embedding_model=embedding_variant(settings),
        )
    )


def api(
    network: DockerNetwork, path: str, body: dict[str, object] | None = None
) -> Command:
    """curl one Ollama API call; a body makes it a POST."""
    data = ["-d", json.dumps(body)] if body is not None else []
    return Command(args=["curl", "-sS", *data, f"{base_url(network)}{path}"])


def parse[M: BaseModel](text: str, model: type[M]) -> M | str:
    """Ollama's JSON as ``model``, or the raw text when it isn't (a curl
    error, or Ollama's own {"error": ...})."""
    try:
        return model.model_validate_json(text)
    except ValidationError:
        return text.strip() or "no answer"


def listeners(run: Runner) -> list[str]:
    """Ollama's listening sockets as `address:port`."""
    out = run(Command(args=["ss", "-Htln", f"( sport = :{OLLAMA_PORT} )"]))
    return [line.split()[3] for line in out.stdout.splitlines()]
