"""Unit tests for the on-prem analyst server page — the two API keys are saved,
the server starts once its uvicorn line is in the log, and its health route
answers from the arcnode network."""

from pathlib import Path

from src.wizard.analyst_server_service import AnalystServerService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import AnalystServerKeys, Deployment

KEYS = AnalystServerKeys(
    openweathermap_api_key="owm-key-1234",
    gridstatus_api_key="grid-key-1234",
)


def make_analyst_server(tmp_path: Path, runner: FakeRunner) -> AnalystServerService:
    return AnalystServerService(
        deployment=Deployment.ON_PREM,
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
