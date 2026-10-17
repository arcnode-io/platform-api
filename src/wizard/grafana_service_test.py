"""Unit tests for the on-prem Grafana page — the admin password is saved for
Grafana and the admin login is verified without it reaching argv."""

from pathlib import Path

from src.wizard.grafana_service import GrafanaService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import PasswordRequest

PASSWORD = "Grafana-pw-1!"


def make_grafana_service(tmp_path: Path, runner: FakeRunner) -> GrafanaService:
    """A GrafanaService on tmp_path."""
    return GrafanaService(
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )


def test_apply_saves_the_password_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_grafana_service(tmp_path, FakeRunner())

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Grafana answers", True),
        ("Admin login works", True),
        ("Saved for the EMS services", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("grafana")


def test_password_never_reaches_argv(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_grafana_service(tmp_path, runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    for command in runner.calls:
        assert PASSWORD not in " ".join(command.args)


def test_grafana_data_dir_is_owned_by_the_grafana_user(tmp_path: Path) -> None:
    """The Grafana image runs as uid 472; a root-owned data dir fails its startup."""
    # Arrange
    runner = FakeRunner()
    service = make_grafana_service(tmp_path, runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    chowns = [c.args for c in runner.calls if c.args[:1] == ["chown"]]
    assert [
        "chown",
        "-R",
        "472:472",
        str(tmp_path / "opt" / "observability" / "grafana-data"),
    ] in chowns
