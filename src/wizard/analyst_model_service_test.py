"""Unit tests for the on-prem analyst model page — its overlay comes from the
order's site, the scheduler starts on the arcnode network, and the page is
done once the file is on disk and the scheduler line is in the log."""

from pathlib import Path

import yaml

from src.wizard.analyst_model_service import AnalystModelService
from src.wizard.ems_cfg import ANALYST_MODEL_CFG_FILE
from src.wizard.site_fixtures import TEST_ORDER
from src.wizard.wizard_fixtures import FakeRunner, tracker
from src.wizard.wizard_record import Deployment


def test_analyst_model_writes_its_overlay_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = AnalystModelService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        order_dir=TEST_ORDER,
        ems_dir=tmp_path / "opt",
        run=FakeRunner(),
    )

    # Act
    result = service.apply()

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Analyst model container running", True),
        ("Scheduler started", True),
        ("MLflow reachable from the analyst model", True),
        ("Saved for the analyst model", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("analyst_model")
    written = yaml.safe_load((tmp_path / "opt" / ANALYST_MODEL_CFG_FILE).read_text())
    assert written == {
        "site_id": "test_site",
        "mlflow_tracking_uri": "http://mlflow:5000",
    }
