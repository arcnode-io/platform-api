"""Unit tests for the on-prem compose override and the log-line readiness gate."""

from pathlib import Path

import pytest
import yaml

from src.wizard import containers_compose
from src.wizard.containers_compose import ONPREM_OVERRIDE, wait_for_log
from src.wizard.wizard_record import Command, CommandOutput

EMS_DIR = Path("/opt/arcnode")
GATEWAY = "industrial-gateway"
SUBSCRIBED = "MQTT subscriptions established"


def test_override_puts_every_service_on_the_arcnode_network() -> None:
    # Arrange
    expected = {"default": {"name": "arcnode", "external": True}}

    # Act
    actual = yaml.safe_load(ONPREM_OVERRIDE)["networks"]

    # Assert
    assert actual == expected


class ScriptedRunner:
    """Answers each call with the first still-unused script entry whose needle matches."""

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self._script = list(script)
        self.calls: list[list[str]] = []

    def __call__(self, command: Command) -> CommandOutput:
        self.calls.append(command.args)
        joined = " ".join(command.args)
        for i, (needle, out) in enumerate(self._script):
            if needle in joined:
                del self._script[i]
                return CommandOutput(returncode=0, stdout=out)
        raise AssertionError(f"unexpected call: {joined}")


def test_wait_for_log_keeps_waiting_through_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container that restarts once during startup is alive, not dead: the wait
    goes on until the line shows up. Seen on the gateway page: the first apply ran
    its checks before the gateway had subscribed, and "Try again" always passed."""
    # Arrange
    monkeypatch.setattr(containers_compose, "POLL_SECONDS", 0)
    run = ScriptedRunner(
        [
            (f"logs {GATEWAY}", ""),
            (f"ps -q -a {GATEWAY}", "abc123\n"),
            ("inspect", "restarting\n"),
            (f"logs {GATEWAY}", ""),
            (f"ps -q -a {GATEWAY}", "abc123\n"),
            ("inspect", "running\n"),
            (f"logs {GATEWAY}", f"initial spec fetched\n{SUBSCRIBED}\n"),
        ]
    )

    # Act
    ready = wait_for_log(run, EMS_DIR, GATEWAY, SUBSCRIBED)

    # Assert
    assert ready is True
    assert len(run.calls) == 7


def test_wait_for_log_gives_up_when_the_container_has_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(containers_compose, "POLL_SECONDS", 0)
    run = ScriptedRunner(
        [
            (f"logs {GATEWAY}", "boot\n"),
            (f"ps -q -a {GATEWAY}", "abc123\n"),
            ("inspect", "exited\n"),
        ]
    )

    # Act
    ready = wait_for_log(run, EMS_DIR, GATEWAY, SUBSCRIBED)

    # Assert
    assert ready is False
