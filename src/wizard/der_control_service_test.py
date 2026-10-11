"""Unit tests for the on-prem DER control API page — its overlay carries the
order's site and the box's address, the service starts, and its health answers."""

from pathlib import Path

import yaml

from src.wizard.der_control_service import DerControlService
from src.wizard.ems_cfg import DER_CONTROL_CFG_FILE
from src.wizard.site_fixtures import TEST_ORDER
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import Deployment, DerControlRequest


def make_der_control(tmp_path: Path) -> DerControlService:
    return DerControlService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        order_dir=TEST_ORDER,
        ems_dir=tmp_path / "opt",
        run=FakeRunner(),
    )


def test_der_control_writes_its_overlay_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = make_der_control(tmp_path)

    # Act
    result = service.apply(DerControlRequest(utility_mirror_url=None))

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("DER control API running", True),
        ("DER control API healthy", True),
        ("Saved for the DER control API", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("der_control_api")
    written = yaml.safe_load((tmp_path / "opt" / DER_CONTROL_CFG_FILE).read_text())
    assert written == {"siteId": "test_site", "publicBaseUrl": "https://10.0.0.209:8443"}


def test_utility_url_is_written_when_the_customer_gives_one(tmp_path: Path) -> None:
    # Arrange
    service = make_der_control(tmp_path)

    # Act
    service.apply(DerControlRequest(utility_mirror_url="https://derms.utility.example"))

    # Assert
    written = yaml.safe_load((tmp_path / "opt" / DER_CONTROL_CFG_FILE).read_text())
    assert written["utilityMirrorUrl"] == "https://derms.utility.example"


def test_skipping_the_der_page_lets_the_wizard_continue(tmp_path: Path) -> None:
    # Arrange — the utility isn't connected yet; the customer moves on
    service = make_der_control(tmp_path)

    # Act
    result = service.skip()

    # Assert
    assert result.verified
    assert [c.name for c in result.checks] == ["Skipped for now"]
    assert tracker(tmp_path).is_done("der_control_api")
