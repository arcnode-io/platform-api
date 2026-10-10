"""Unit tests for the on-prem HiveMQ page — broker accounts written to the
credentials file and secrets.env, the broker started on the arcnode network,
and every account's login verified."""

from pathlib import Path

from src.wizard.hivemq_fixtures import TEMPLATE_TEXT
from src.wizard.hivemq_service import HivemqService
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import BrokerPasswords, Deployment

PASSWORDS = BrokerPasswords(
    service="Service-pw-1!",
    operator="Operator-pw-1!",
    viewer="Viewer-pw-1!",
)



def make_hivemq_service(tmp_path: Path, runner: FakeRunner) -> HivemqService:
    """A HivemqService on tmp_path, with the template already on the box."""
    (tmp_path / "opt").mkdir(exist_ok=True)
    (tmp_path / "opt" / "credentials.template.xml").write_text(TEMPLATE_TEXT)
    return HivemqService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )


def test_apply_starts_the_broker_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_hivemq_service(tmp_path, FakeRunner())

    # Act
    result = service.apply(PASSWORDS)

    # Assert
    actual_rows = [(check.name, check.ok) for check in result.checks]
    assert actual_rows == [
        ("HiveMQ container running", True),
        ("Refuses anonymous logins", True),
        ("Accepts each account's password", True),
        ("Saved for the EMS services", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("hivemq")


def test_service_password_fills_all_four_service_accounts(tmp_path: Path) -> None:
    # Arrange
    service = make_hivemq_service(tmp_path, FakeRunner())

    # Act
    service.apply(PASSWORDS)

    # Assert — the template has one password slot per service account, and the
    # four services share the one service password
    credentials = (tmp_path / "opt" / "credentials.xml").read_text()
    assert credentials.count(PASSWORDS.service) == 4
    assert PASSWORDS.operator in credentials and PASSWORDS.viewer in credentials


def test_no_password_reaches_argv(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_hivemq_service(tmp_path, runner)

    # Act
    service.apply(PASSWORDS)

    # Assert — argv is visible to every user through ps
    for command in runner.calls:
        for password in PASSWORDS.model_dump().values():
            assert password not in " ".join(command.args)

