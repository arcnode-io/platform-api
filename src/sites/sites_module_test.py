"""The sites endpoint exists only where there is a DNS zone to write: production (site_dns on)."""

import os

import pytest

from src.app_module import AppModule
from src.config import load_config

ROUTE = "/platform-api/sites/{order_id}/address"


def _paths(module: AppModule) -> set[str]:
    """The served paths, read from the OpenAPI schema (included routers are lazy objects)."""
    return set(module.create_app().openapi()["paths"])


def test_the_address_callback_is_served_when_site_dns_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("ENV", "local")
    monkeypatch.setenv("NAMECHEAP_API_KEY", "nc-key")
    monkeypatch.setenv("SITE_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("PRESIGN_ACCESS_KEY_ID", "AKIDTEST")
    monkeypatch.setenv("PRESIGN_SECRET_ACCESS_KEY", "secret-for-test")
    config = load_config().model_copy(update={"site_dns": True})

    # Act
    paths = _paths(AppModule(config))

    # Assert
    assert ROUTE in paths


def test_the_address_callback_is_absent_and_needs_no_secrets_when_it_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — local dev and the test suites have no zone and no keys
    monkeypatch.setenv("ENV", "local")
    monkeypatch.delenv("NAMECHEAP_API_KEY", raising=False)
    monkeypatch.delenv("SITE_TOKEN_SECRET", raising=False)
    config = load_config().model_copy(update={"site_dns": False})

    # Act
    paths = _paths(AppModule(config))

    # Assert
    assert ROUTE not in paths
    assert "SITE_TOKEN_SECRET" not in os.environ
