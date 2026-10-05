"""HTTP-layer tests for the wizard controller — real requests through
FastAPI's own request validation, not just WizardService called directly.

wizard_service_test.py already covers the business logic; this file covers
what reaching it over HTTP actually validates/rejects, since that's a
different layer (pydantic request parsing, status codes) that a direct
service call bypasses entirely.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wizard.wizard_module import WizardModule

VALID_PASSWORD = "Testpass1!"
# 7 characters — one under the 8-char minimum, otherwise policy-compliant
# (has upper/digit/special) — isolates the length check specifically.
TOO_SHORT_PASSWORD = "Tsp1!ab"


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(WizardModule(base_dir=tmp_path).router)
    return TestClient(app)


def _payload(*, operator_password: str, viewer_password: str) -> dict:
    return {
        "api_keys": {},
        "tls": {"mode": "selfsigned", "cert_pem": None, "key_pem": None},
        "human_auth": {
            "operator_password": operator_password,
            "operator_confirm": operator_password,
            "viewer_password": viewer_password,
            "viewer_confirm": viewer_password,
        },
    }


def test_apply_accepts_valid_password_length(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
    payload = _payload(operator_password=VALID_PASSWORD, viewer_password=VALID_PASSWORD)

    # Act
    response = client.post("/setup/api/apply", json=payload)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Setup applied."}


def test_apply_rejects_password_one_char_under_minimum(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
    payload = _payload(
        operator_password=TOO_SHORT_PASSWORD, viewer_password=TOO_SHORT_PASSWORD
    )

    # Act
    response = client.post("/setup/api/apply", json=payload)

    # Assert
    assert response.status_code == 422
    errors = response.json()["detail"]
    rejected_fields = {tuple(err["loc"]) for err in errors}
    assert ("body", "human_auth", "operator_password") in rejected_fields
    assert ("body", "human_auth", "viewer_password") in rejected_fields


def test_setup_page_404s_after_apply(tmp_path: Path) -> None:
    # Arrange
    client = _client(tmp_path)
    payload = _payload(operator_password=VALID_PASSWORD, viewer_password=VALID_PASSWORD)
    client.post("/setup/api/apply", json=payload)

    # Act
    response = client.get("/setup")

    # Assert
    assert response.status_code == 404
