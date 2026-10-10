"""The on-prem Ollama page: listen on the arcnode gateway only, download the
models (streaming progress to the browser — tens of GB), create the
embedding model's 8k-context variant, load both for good, point ems-analyst
at them, verify. The binary itself was installed (and left off) by
src/iso/phases/ollama.sh."""

import json
import time
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Final


from src.wizard.docker_verify import missing_network_check, read_network
from src.wizard.ems_cfg import update_analyst_cfg
from src.wizard.ollama_record import OllamaPageEvent, PullLine, PullProgress
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
from src.wizard.ollama_verify import verify_ollama
from src.wizard.system_runner import LineStream, Runner
from src.wizard.wizard_record import (
    Command,
    Deployment,
    DockerNetwork,
    OllamaSettings,
    StepResult,
    WizardConfig,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

DROP_IN: Final[str] = "/etc/systemd/system/ollama.service.d/arcnode.conf"
# Poll interval for the readiness gate below — not a timeout.
POLL_SECONDS: Final[float] = 0.5


class OllamaStepNotAvailableError(Exception):
    """No Ollama page in the cloud — the LLM is Bedrock."""


class OllamaService:
    """Everything ems-analyst needs from the host's Ollama."""

    def __init__(
        self,
        *,
        config: WizardConfig,
        tracker: StepTracker,
        analyst_cfg_path: Path,
        run: Runner,
        stream: LineStream,
    ) -> None:
        self._config = config
        self._tracker = tracker
        self._analyst_cfg_path = analyst_cfg_path
        self._run = run
        self._stream = stream

    def apply(self) -> Iterator[OllamaPageEvent]:
        """Refuse up front (before any streaming starts), then return the
        page's event stream: progress lines, then one result."""
        settings = self._config.ollama
        if self._config.deployment == Deployment.CLOUD or settings is None:
            raise OllamaStepNotAvailableError("no Ollama step in the cloud")
        if self._tracker.is_done("ollama"):
            raise StepAlreadyDoneError("Ollama is already set up")
        return self._page(settings)

    def _page(self, settings: OllamaSettings) -> Iterator[OllamaPageEvent]:
        network = read_network(self._run)
        if network is None:
            yield _result(StepResult(verified=False, checks=[missing_network_check()]))
            return
        self._configure(network, settings)
        if self._wait_for_api(network):
            pulled = True
            for model in (settings.chat_model, settings.embedding_model):
                pulled = pulled and (yield from self._pull(network, model))
            if pulled:
                self._prepare(network, settings)
        checks = verify_ollama(self._run, self._config, network, self._analyst_cfg_path)
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("ollama")
        yield _result(StepResult(verified=verified, checks=checks))

    def _configure(self, network: DockerNetwork, settings: OllamaSettings) -> None:
        """Drop-in env (gateway, context, both models resident), then start."""
        drop_in = (
            "[Service]\n"
            f'Environment="OLLAMA_HOST={network.gateway}:{OLLAMA_PORT}"\n'
            f'Environment="OLLAMA_CONTEXT_LENGTH={settings.context_length}"\n'
            # Two analyst requests at once, each with the full context.
            'Environment="OLLAMA_NUM_PARALLEL=2"\n'
            'Environment="OLLAMA_KV_CACHE_TYPE=f16"\n'
            # Never unload: the EMS shouldn't wait on a cold model.
            'Environment="OLLAMA_KEEP_ALIVE=-1"\n'
        )
        self._run(Command(args=["mkdir", "-p", str(Path(DROP_IN).parent)]))
        self._run(Command(args=["tee", DROP_IN], input=drop_in))
        self._run(Command(args=["systemctl", "daemon-reload"]))
        self._run(Command(args=["systemctl", "enable", OLLAMA_UNIT]))
        self._run(Command(args=["systemctl", "restart", OLLAMA_UNIT]))

    def _wait_for_api(self, network: DockerNetwork) -> bool:
        """Readiness gate: the port opens once the server is up; stop the
        moment the unit dies instead."""
        while f"{network.gateway}:{OLLAMA_PORT}" not in listeners(self._run):
            state = self._run(Command(args=["systemctl", "is-active", OLLAMA_UNIT]))
            if state.stdout.strip() not in ("active", "activating"):
                return False
            time.sleep(POLL_SECONDS)
        return True

    def _pull(
        self, network: DockerNetwork, model: str
    ) -> Generator[OllamaPageEvent, None, bool]:
        """Stream one model's download; False on Ollama's in-band error."""
        url = f"{base_url(network)}/api/pull"
        body = json.dumps({"model": model})
        for text in self._stream(Command(args=["curl", "-sSN", "-d", body, url])):
            line = parse(text, PullLine)
            if isinstance(line, str) or line.error:
                status = line if isinstance(line, str) else line.error
                yield _progress(PullProgress(model=model, status=f"error: {status}"))
                return False
            yield _progress(
                PullProgress(
                    model=model,
                    status=line.status,
                    completed=line.completed,
                    total=line.total,
                )
            )
        return True

    def _prepare(self, network: DockerNetwork, settings: OllamaSettings) -> None:
        """8k embedding variant, both models loaded for good, analyst cfg."""
        variant = embedding_variant(settings)
        create: dict[str, object] = {
            "model": variant,
            "from": settings.embedding_model,
            "parameters": {"num_ctx": EMBED_CONTEXT},
            "stream": False,
        }
        self._run(api(network, "/api/create", create))
        load: dict[str, object] = {"model": settings.chat_model, "keep_alive": -1}
        self._run(api(network, "/api/generate", load))
        warm: dict[str, object] = {
            "model": variant,
            "input": "warmup",
            "keep_alive": -1,
        }
        self._run(api(network, "/api/embed", warm))
        # Reason: merge — the Site page writes the same file's other keys.
        update_analyst_cfg(self._analyst_cfg_path, analyst_cfg(network, settings))


def _progress(progress: PullProgress) -> OllamaPageEvent:
    return OllamaPageEvent(progress=progress)


def _result(result: StepResult) -> OllamaPageEvent:
    return OllamaPageEvent(result=result)
