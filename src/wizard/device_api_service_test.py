"""Unit tests for the on-prem Device API page — the secrets it signs with are
saved, the topology it loads matches the order, and no secret reaches argv."""

from pathlib import Path

from src.wizard.device_api_service import DeviceApiService
from src.wizard.site_fixtures import TEST_ORDER
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import Deployment, DeviceApiSecrets

SECRETS = DeviceApiSecrets(
    jwt_secret="x" * 40,
    operator_password="Operator-pw-1!",
    viewer_password="Viewer-pw-1!",
)


def make_device_api_service(tmp_path: Path, runner: FakeRunner) -> DeviceApiService:
    """A service on tmp_path, with the order's topology in place as the Site page left it."""
    ems_dir = tmp_path / "opt"
    ems_dir.mkdir(exist_ok=True)
    (ems_dir / "dtm.json").write_text((TEST_ORDER / "dtm.json").read_text())
    # Reason: the fake curl answers with the order's topology, as the real API would.
    topology_key = "device-api:3000/topology"
    # Reason: a dict literal keeps the later value for a repeated key, so drop the fixture's default first.
    runner.queries = {
        topology_key: ok((TEST_ORDER / "dtm.json").read_text()),
        **{k: v for k, v in runner.queries.items() if k != topology_key},
    }
    return DeviceApiService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        ems_dir=ems_dir,
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )


def test_apply_saves_secrets_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_device_api_service(tmp_path, FakeRunner())

    # Act
    result = service.apply(SECRETS)

    # Assert
    actual_rows = [(check.name, check.ok) for check in result.checks]
    assert actual_rows == [
        ("Device API answers", True),
        ("Serves its message spec", True),
        ("Operator can log in", True),
        ("Topology loaded", True),
        ("Connected to the broker", True),
        ("Saved for the EMS services", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("device_api")


def test_no_secret_reaches_argv(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_device_api_service(tmp_path, runner)

    # Act
    service.apply(SECRETS)

    # Assert — the login body travels on stdin, the rest through the env file
    for command in runner.calls:
        for secret in (
            SECRETS.jwt_secret,
            SECRETS.operator_password,
            SECRETS.viewer_password,
        ):
            assert secret not in " ".join(command.args)
