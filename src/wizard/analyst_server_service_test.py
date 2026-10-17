"""Unit tests for the on-prem analyst server page — the two API keys are saved,
the server starts once its uvicorn line is in the log, and its health route
answers from the arcnode network."""

import json
from pathlib import Path

from src.wizard.analyst_server_service import AnalystServerService
from src.wizard.controller_fixtures import wizard_client
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import (
    AnalystServerKeys,
    Command,
    CommandOutput,
)

KEYS = AnalystServerKeys(
    openweathermap_api_key="owm-key-1234",
    gridstatus_api_key="grid-key-1234",
)


def make_analyst_server(tmp_path: Path, runner: FakeRunner) -> AnalystServerService:
    return AnalystServerService(
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )


def test_analyst_server_saves_keys_starts_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = make_analyst_server(tmp_path, FakeRunner())

    # Act
    result = service.apply(KEYS)

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Analyst server running", True),
        ("Analyst server health", True),
        ("Saved for the EMS services", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("analyst_server")
    saved = (tmp_path / "secrets.env").read_text()
    assert "OPENWEATHERMAP_API_KEY=owm-key-1234" in saved
    assert "GRIDSTATUS_API_KEY=grid-key-1234" in saved


def test_no_key_reaches_argv(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_analyst_server(tmp_path, runner)

    # Act
    service.apply(KEYS)

    # Assert — argv is visible to every user through ps
    for command in runner.calls:
        for key in (KEYS.openweathermap_api_key, KEYS.gridstatus_api_key):
            assert key not in " ".join(command.args)


def test_progress_reports_each_stage_from_the_container_logs(tmp_path: Path) -> None:
    # Arrange — the fake's analyst logs carry only the uvicorn line, so only the last stage is done
    service = make_analyst_server(tmp_path, FakeRunner())

    # Act
    stages = service.progress()

    # Assert
    assert [s.done for s in stages] == [False, False, False, True]


def test_progress_route_returns_each_stage_as_an_object(tmp_path: Path) -> None:
    # Arrange — the page reads stage.label, stage.done and stage.phase, so each stage must be a JSON object
    client = wizard_client(tmp_path, runner=FakeRunner())

    # Act
    stages = client.get("/api/analyst-server/progress").json()

    # Assert
    assert set(stages[0]) == {
        "label",
        "done",
        "phase",
        "percent",
        "eta_seconds",
        "mib_done",
        "mib_total",
    }
    assert stages[0]["label"] == "Packages installed"


def test_start_streams_stage_updates_then_the_verdict(tmp_path: Path) -> None:
    """The apply request streams progress as it runs, so the connection stays alive while the seed
    downloads; the last line carries the verdict."""
    # Arrange
    service = make_analyst_server(tmp_path, FakeRunner())

    # Act
    lines = list(service.start_stream(KEYS))

    # Assert — stage updates first, then one verdict line
    assert len(lines) >= 2
    assert '"stages"' in lines[0]
    final = json.loads(lines[-1])
    assert final["result"]["verified"] is True


class RestartingThenReady(FakeRunner):
    """The analyst container is mid-restart while its logs are still short, then comes up:
    the first progress read sees 'restarting', later ones see the full log."""

    def __init__(self) -> None:
        super().__init__()
        self._log_reads = 0

    def __call__(self, command: Command) -> CommandOutput:
        text = " ".join(command.args)
        if "logs analyst-server" in text:
            self.calls.append(command)
            self._log_reads += 1
            if self._log_reads == 1:
                return CommandOutput(returncode=0, stdout="Installed 42 packages\n")
            return CommandOutput(
                returncode=0,
                stdout="vector slice seeded\ngraph slice seeded\n"
                "Uvicorn running on http://0.0.0.0:8000\n",
            )
        if "--status running" in text and self._log_reads <= 1:
            # What real docker prints for the moment a restart takes: nothing.
            self.calls.append(command)
            return CommandOutput(returncode=0, stdout="")
        if "inspect --format" in text and self._log_reads <= 1:
            self.calls.append(command)
            return CommandOutput(returncode=0, stdout="restarting\n")
        return super().__call__(command)


def test_start_keeps_streaming_while_the_container_restarts(tmp_path: Path) -> None:
    """A restart is not a crash: the stream goes on until the ready line, instead of
    ending in a false 'not running' failure halfway through the seed."""
    # Arrange
    service = make_analyst_server(tmp_path, RestartingThenReady())

    # Act
    lines = [json.loads(line) for line in service.start_stream(KEYS)]

    # Assert — more than one stage update, and the verdict is the success
    assert len([line for line in lines if "stages" in line]) >= 2
    assert lines[-1]["result"]["verified"] is True
