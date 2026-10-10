"""Integration test: the real install-time phases (docker.sh, then
ollama.sh) on a real Debian 13 container with a real dockerd, then the real
Docker page and the real Ollama page, in dependency order — with the tiny
models test-mode.sh uses, on CPU. Ollama moves onto the gateway Docker
actually picked, downloads (streaming progress), loads both models, and a
real container on that network embeds.

Only `systemctl` is stood in for (containers have no systemd): restart runs
the unit's ExecStart as the ollama user with the unit + drop-in env.
Downloaded models are cached in a named volume between runs.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from testcontainers.core.container import DockerContainer

from src.wizard.docker_service import DockerService
from src.wizard.ollama_fixtures import PRODUCTION
from src.wizard.ollama_service import OllamaService
from src.wizard.system_runner import LineStream, Runner
from src.wizard.wizard_record import (
    Command,
    CommandOutput,
    Deployment,
    HardwareMinimums,
    OllamaSettings,
)
from src.wizard.wizard_steps import StepTracker

PHASES: Final[Path] = Path(__file__).parent.parent / "src" / "iso" / "phases"
MODELS_VOLUME: Final[str] = "arcnode-test-ollama-models"
# Readiness gate, not a guessed timeout: wait for the socket to answer,
# and fail fast the moment dockerd itself is gone.
WAIT_FOR_DOCKERD: Final[str] = (
    "until docker info >/dev/null 2>&1; do "
    "pidof dockerd >/dev/null || { tail -20 /tmp/dockerd.log; exit 1; }; "
    "sleep 0.2; done"
)
# The unit's env plus the wizard's drop-in, then the unit's ExecStart.
START_OLLAMA: Final[str] = (
    "pkill -x ollama; while pgrep -x ollama >/dev/null; do sleep 0.1; done; "
    "env $(sed -n 's/^Environment=\"\\(.*\\)\"/\\1/p' "
    "/etc/systemd/system/ollama.service /etc/systemd/system/ollama.service.d/arcnode.conf) "
    "runuser -u ollama -- /usr/bin/ollama serve >/tmp/ollama.log 2>&1 &"
)
SYSTEMCTL: Final[dict[tuple[str, ...], list[str]]] = {
    ("daemon-reload",): ["true"],
    ("enable", "ollama"): ["true"],
    ("restart", "ollama"): ["sh", "-c", START_OLLAMA],
    ("is-active", "ollama"): ["pgrep", "-x", "ollama"],
    ("is-active", "docker"): ["docker", "info"],
}
# test-mode.sh's profile — a CPU-only box.
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


def _container_runner(container: DockerContainer) -> Runner:
    """Run each wizard Command inside the container, stdin/env intact."""
    docker = container.get_wrapped_container()

    def run(command: Command) -> CommandOutput:
        args = command.args
        if args[0] == "systemctl":
            code, _ = docker.exec_run(SYSTEMCTL[tuple(args[1:])])
            state = "active\n" if code == 0 else "inactive\n"
            return CommandOutput(returncode=code, stdout=state)
        env = dict(command.env)
        if command.input is not None:
            env["ARCNODE_STDIN"] = command.input
            args = ["sh", "-c", 'printf "%s" "$ARCNODE_STDIN" | "$@"', "sh", *args]
        code, output = docker.exec_run(args, environment=env)
        return CommandOutput(returncode=code, stdout=output.decode())

    return run


def _container_stream(container: DockerContainer) -> LineStream:
    """Stream a command's output inside the container, line by line."""
    docker = container.get_wrapped_container()

    def stream(command: Command) -> Iterator[str]:
        buffer = ""
        for chunk in docker.exec_run(command.args, stream=True).output:
            buffer += chunk.decode()
            *lines, buffer = buffer.split("\n")
            yield from lines
        if buffer:
            yield buffer

    return stream


def _exec(container: DockerContainer, script: str) -> str:
    code, output = container.get_wrapped_container().exec_run(
        ["sh", "-c", script], environment={"DEBIAN_FRONTEND": "noninteractive"}
    )
    assert code == 0, output.decode()[-3000:]
    return output.decode()


@pytest.fixture(scope="module")
def installed() -> Iterator[DockerContainer]:
    """Debian 13 with both real phases applied and dockerd up; Ollama is
    installed but off, as the install leaves it."""
    # Reason: privileged to run dockerd at all; /var/lib/docker on tmpfs
    # because overlayfs can't stack on the outer container's overlayfs.
    container = (
        DockerContainer("debian:trixie")
        .with_command("sleep infinity")
        .with_kwargs(privileged=True, tmpfs={"/var/lib/docker": ""})
        .with_volume_mapping(MODELS_VOLUME, "/var/lib/ollama/models", "rw")
    )
    container.start()
    try:
        # iproute2 (ss) + procps (pgrep) ship with every real Debian install.
        _exec(container, "apt-get update -qq && apt-get install -y -qq iproute2 procps")
        _exec(container, (PHASES / "docker.sh").read_text())
        _exec(container, (PHASES / "ollama.sh").read_text())
        container.get_wrapped_container().exec_run(
            ["sh", "-c", "dockerd >/tmp/dockerd.log 2>&1"], detach=True
        )
        _exec(container, WAIT_FOR_DOCKERD)
        yield container
    finally:
        container.stop()


def test_install_leaves_ollama_off(installed: DockerContainer) -> None:
    # Act
    wants = _exec(installed, "ls /etc/systemd/system/multi-user.target.wants/ || true")
    version = _exec(installed, "/usr/bin/ollama --version || true")

    # Assert: installed, but no Ollama on any address until the wizard says so
    assert "ollama" not in wants
    assert "0.34.4" in version


def test_real_ollama_on_dockers_gateway_passes_every_check(
    installed: DockerContainer, tmp_path: Path
) -> None:
    # Arrange: the Docker page first — it creates the network Ollama listens on
    run = _container_runner(installed)
    tracker = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM)
    assert (
        DockerService(deployment=Deployment.ON_PREM, tracker=tracker, run=run)
        .apply()
        .verified
    )
    service = OllamaService(
        config=TEST_BOX,
        tracker=tracker,
        analyst_cfg_path=tmp_path / "analyst-cfg.customer.yml",
        run=run,
        stream=_container_stream(installed),
    )

    # Act
    events = list(service.apply())

    # Assert
    progress = [e.progress for e in events if e.progress]
    result = events[-1].result
    assert result is not None
    actual = {check.name: (check.ok, check.detail) for check in result.checks}
    assert [p.status for p in progress if p.model == "qwen3:0.6b"][-1] == "success"
    assert all(ok for ok, _ in actual.values()), actual
    assert result.verified
