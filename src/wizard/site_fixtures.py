"""Fixtures for the Site page tests — imported explicitly (no conftest)."""

import shutil
from pathlib import Path
from typing import Final

from src.wizard.site_service import SiteService
from src.wizard.wizard_fixtures import tracker

# The order test-mode.sh installs — real edp-api output, so tests run on it.
TEST_ORDER: Final[Path] = Path(__file__).parent.parent / "iso" / "phases" / "test-order"


def make_site_service(
    tmp_path: Path,
    *,
    order: Path | None = TEST_ORDER,
) -> SiteService:
    """A Site page over tmp dirs; ``order=None`` is a box with no order."""
    order_dir = tmp_path / "order"
    if order is not None:
        shutil.copytree(order, order_dir)
    ems_dir = tmp_path / "opt-arcnode"
    return SiteService(
        tracker=tracker(tmp_path),
        order_dir=order_dir,
        ems_dir=ems_dir,
        analyst_cfg_path=ems_dir / "analyst-cfg.customer.yml",
    )
