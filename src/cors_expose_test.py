"""The site's browser can read Retry-After from a cross-origin response; CORS hides it otherwise."""

import pytest
from fastapi.testclient import TestClient

from src.app_module import AppModule
from src.config import load_config


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ENV", "local")
    return TestClient(AppModule(load_config()).create_app())


def test_retry_after_is_exposed_to_the_site_origin(client: TestClient) -> None:
    # Arrange + Act — an actual cross-origin response (preflight never carries exposed headers)
    response = client.get("/", headers={"Origin": "https://arcnode.io"})

    # Assert
    assert "Retry-After" in response.headers.get("access-control-expose-headers", "")
