"""Playbook-style verification for the Ollama page — each check a row the
UI shows, with the console command that debugs it."""

import json
from pathlib import Path
from typing import Final

from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.ollama_api import (
    EMBED_CONTEXT,
    OLLAMA_PORT,
    OLLAMA_UNIT,
    analyst_cfg,
    api,
    base_url,
    embedding_variant,
    listeners,
    parse,
)
from src.wizard.ems_cfg import AnalystCfg, read_analyst_cfg
from src.wizard.ollama_record import (
    Embeddings,
    Generated,
    LoadedModel,
    LoadedModels,
    OllamaTags,
)
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    DockerNetwork,
    OllamaSettings,
    VerifyCheck,
    WizardConfig,
)

# Pinned: the "a container embeds" probe, curl from the arcnode network.
PROBE_IMAGE: Final[str] = "curlimages/curl:8.22.0"
PROBE_RUN: Final[str] = f"docker run --rm --network {DOCKER_NETWORK} {PROBE_IMAGE}"
LOG_HINT: Final[str] = "sudo systemctl status ollama; sudo journalctl -u ollama -n 50"
ANSWER_PROMPT: Final[str] = "Reply with OK"


def verify_ollama(
    run: Runner, config: WizardConfig, network: DockerNetwork, analyst_cfg_path: Path
) -> list[VerifyCheck]:
    """Running → gateway only → models downloaded → each loaded with its
    context (on the GPU when the box has one) → chat answers → a container
    embeds → analyst config saved."""
    settings = config.ollama
    assert settings is not None  # nosec B101 — the service refuses without it
    loaded = parse(run(api(network, "/api/ps")).stdout, LoadedModels)
    gpus = config.hardware.gpus
    return [
        _running(run),
        _listens(run, network),
        _downloaded(run, settings, network),
        _loaded(
            "Chat model loaded",
            loaded,
            settings.chat_model,
            settings.context_length,
            gpus,
        ),
        _loaded(
            "Embedding model loaded",
            loaded,
            embedding_variant(settings),
            EMBED_CONTEXT,
            gpus,
        ),
        _answers(run, settings, network),
        _container_embeds(run, settings, network),
        _analyst_cfg_saved(analyst_cfg_path, analyst_cfg(network, settings)),
    ]


def _running(run: Runner) -> VerifyCheck:
    state = run(Command(args=["systemctl", "is-active", OLLAMA_UNIT])).stdout.strip()
    return VerifyCheck(
        name="Ollama running", ok=state == "active", detail=state, hint=LOG_HINT
    )


def _listens(run: Runner, network: DockerNetwork) -> VerifyCheck:
    found = listeners(run)
    expected = [f"{network.gateway}:{OLLAMA_PORT}"]
    return VerifyCheck(
        name="Listens on Docker's gateway only",
        ok=found == expected,
        detail=", ".join(found) or "not listening",
        hint=f"sudo ss -tlnp '( sport = :{OLLAMA_PORT} )'; "
        "cat /etc/systemd/system/ollama.service.d/arcnode.conf",
    )


def _downloaded(
    run: Runner, settings: OllamaSettings, network: DockerNetwork
) -> VerifyCheck:
    tags = parse(run(api(network, "/api/tags")).stdout, OllamaTags)
    names = [tag.name for tag in tags.models] if isinstance(tags, OllamaTags) else []
    wanted = [settings.chat_model, embedding_variant(settings)]
    missing = [name for name in wanted if name not in names]
    return VerifyCheck(
        name="Models downloaded",
        ok=not missing,
        detail=", ".join(wanted) if not missing else f"missing: {', '.join(missing)}",
        hint=f"curl -s {base_url(network)}/api/tags",
    )


def _loaded(
    name: str, loaded: LoadedModels | str, model: str, context: int, gpus: int
) -> VerifyCheck:
    found = (
        next((m for m in loaded.models if m.name == model), None)
        if isinstance(loaded, LoadedModels)
        else None
    )
    hint = "ollama ps; nvidia-smi"
    if found is None:
        return VerifyCheck(
            name=name, ok=False, detail=f"{model} not in memory", hint=hint
        )
    on_gpu = found.size_vram == found.size
    return VerifyCheck(
        name=name,
        ok=found.context_length == context and (on_gpu or gpus == 0),
        detail=f"{model}, {_placement(found)}, context {found.context_length} (need {context})",
        hint=hint,
    )


def _placement(model: LoadedModel) -> str:
    if model.size_vram == 0:
        return "CPU"
    return f"{model.size_vram * 100 // model.size}% GPU"


def _answers(
    run: Runner, settings: OllamaSettings, network: DockerNetwork
) -> VerifyCheck:
    body: dict[str, object] = {
        "model": settings.chat_model,
        "prompt": ANSWER_PROMPT,
        "stream": False,
        "options": {"num_predict": 8},
    }
    reply = parse(run(api(network, "/api/generate", body)).stdout, Generated)
    ok = isinstance(reply, Generated) and reply.eval_count > 0
    return VerifyCheck(
        name="Chat model answers",
        ok=ok,
        detail=f"{reply.eval_count} tokens" if isinstance(reply, Generated) else reply,
        hint=f"ollama run {settings.chat_model} '{ANSWER_PROMPT}'",
    )


def _container_embeds(
    run: Runner, settings: OllamaSettings, network: DockerNetwork
) -> VerifyCheck:
    body = json.dumps({"model": embedding_variant(settings), "input": "ping"})
    url = f"{base_url(network)}/api/embed"
    out = run(Command(args=[*PROBE_RUN.split(), "-sS", "-d", body, url]))
    # Reason: curl's JSON is the last line — anything above it is docker's
    # first-run image pull chatter.
    reply = parse((out.stdout.strip().splitlines() or [""])[-1], Embeddings)
    dims = (
        len(reply.embeddings[0])
        if isinstance(reply, Embeddings) and reply.embeddings
        else 0
    )
    return VerifyCheck(
        name="A container on the arcnode network embeds",
        ok=dims > 0,
        detail=f"{dims} dimensions" if dims else str(reply),
        hint=f"sudo {PROBE_RUN} -s {base_url(network)}/api/tags",
    )


def _analyst_cfg_saved(path: Path, expected: AnalystCfg) -> VerifyCheck:
    ok = read_analyst_cfg(path).settings == expected.settings
    return VerifyCheck(
        name="Saved for the EMS analyst",
        ok=ok,
        detail=str(path) if ok else f"{path} missing or different",
        hint=f"sudo cat {path}",
    )
