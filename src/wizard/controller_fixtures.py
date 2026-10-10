"""The wizard app over tmp dirs, for the HTTP-layer tests — imported
explicitly (no conftest)."""

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wizard.ollama_fixtures import PRODUCTION, FakeStream
from src.wizard.site_fixtures import TEST_ORDER
from src.wizard.hivemq_fixtures import TEMPLATE_TEXT
from src.wizard.wizard_fixtures import FakeRunner, account
from src.wizard.wizard_module import WizardModule
from src.wizard.wizard_record import Deployment


def wizard_client(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    runner: FakeRunner | None = None,
) -> TestClient:
    """The real app, fake commands; the box was installed from an ISO
    carrying the test order."""
    shutil.copytree(TEST_ORDER, tmp_path / "order")
    # Reason: FakeRunner's curl writes nothing, so the template the real curl
    # would have fetched is placed where the HiveMQ page reads it.
    (tmp_path / "opt-arcnode").mkdir(exist_ok=True)
    (tmp_path / "opt-arcnode" / "credentials.template.xml").write_text(TEMPLATE_TEXT)
    app = FastAPI()
    app.include_router(
        WizardModule(
            base_dir=tmp_path,
            secrets_env_path=tmp_path / "secrets.env",
            account=account(tmp_path),
            analyst_cfg_path=tmp_path / "analyst-cfg.customer.yml",
            ems_dir=tmp_path / "opt-arcnode",
            config=PRODUCTION.model_copy(update={"deployment": deployment}),
            run=runner or FakeRunner(),
            stream=FakeStream(),
        ).router
    )
    return TestClient(app)
