"""The first wizard page after the hardware check: the customer confirms the site
identity the configurator baked into this ISO. Read-only; Confirm marks it done."""

from pathlib import Path

import pytest

from src.wizard.identity_service import IdentityService, IdentityStepNotAvailableError
from src.wizard.wizard_fixtures import tracker
from src.wizard.wizard_record import Deployment
from src.wizard.wizard_steps import StepAlreadyDoneError

SITE_YML = (
    "site_id: nevada_facility_2\n"
    "market_region: ercot\n"
    "settlement_point: HB_NORTH\n"
    "customer: Acme Compute\n"
    "site_name: Nevada Facility 2\n"
    "order_id: 6f1c2a9e-0000-4000-8000-000000000042\n"
)


def _service(tmp_path: Path, site_yml: str = SITE_YML) -> IdentityService:
    order = tmp_path / "order"
    order.mkdir()
    (order / "site.yml").write_text(site_yml)
    return IdentityService(
        deployment=Deployment.ON_PREM, tracker=tracker(tmp_path), order_dir=order
    )


def test_info_reports_what_the_configurator_baked_into_the_iso(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    info = service.info()

    # Assert
    assert (info.customer, info.site, info.order_id) == (
        "Acme Compute",
        "Nevada Facility 2",
        "6f1c2a9e-0000-4000-8000-000000000042",
    )
    assert info.market == "ercot · HB_NORTH"


def test_an_order_without_identity_fields_still_reports_its_site_id(
    tmp_path: Path,
) -> None:
    """Generic-ISO / test-mode orders have only the original three fields."""
    # Arrange
    service = _service(tmp_path, "site_id: test_site\nmarket_region: ercot\n")

    # Act
    info = service.info()

    # Assert
    assert (info.customer, info.site, info.order_id) == (None, "test_site", None)
    assert info.market == "ercot"


def test_confirm_marks_the_page_done_once(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    result = service.confirm()

    # Assert
    assert result.verified
    assert tracker(tmp_path).is_done("identity")
    with pytest.raises(StepAlreadyDoneError):
        service.confirm()


def test_the_cloud_has_no_identity_page(tmp_path: Path) -> None:
    # Arrange
    service = IdentityService(
        deployment=Deployment.CLOUD,
        tracker=tracker(tmp_path, Deployment.CLOUD),
        order_dir=tmp_path / "order",
    )

    # Act + Assert
    with pytest.raises(IdentityStepNotAvailableError):
        service.info()
