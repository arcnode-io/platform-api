"""HTTP contract of the box's address callback: POST /platform-api/sites/{order_id}/address."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.sites.site_address_service import (
    InvalidSiteAddressError,
    InvalidSiteTokenError,
    UnknownOrderError,
)
from src.sites.sites_controller import SitesController

ORDER_ID = "6f1c2a9e-0000-4000-8000-000000000042"
URL = f"/platform-api/sites/{ORDER_ID}/address"


class StubService:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[str, str, str]] = []

    async def register(self, *, order_id: str, token: str, address: str) -> str:
        self.calls.append((order_id, token, address))
        if self._error:
            raise self._error
        return "nevada-facility-2-6f1c2a.arcnode.io"


def _client(service: StubService) -> TestClient:
    app = FastAPI()
    app.include_router(SitesController(service=service).router)
    return TestClient(app)


def test_a_valid_callback_returns_the_hostname() -> None:
    # Arrange
    service = StubService()

    # Act
    response = _client(service).post(
        URL, json={"address": "3.228.116.51"}, headers={"X-Site-Token": "tok"}
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == {"hostname": "nevada-facility-2-6f1c2a.arcnode.io"}
    assert service.calls == [(ORDER_ID, "tok", "3.228.116.51")]


def test_each_refusal_has_its_own_status() -> None:
    # Arrange
    cases = [
        (InvalidSiteTokenError("bad"), 403),
        (UnknownOrderError("none"), 404),
        (InvalidSiteAddressError("private"), 422),
    ]

    # Act + Assert
    for error, expected in cases:
        response = _client(StubService(error)).post(
            URL, json={"address": "10.0.0.5"}, headers={"X-Site-Token": "tok"}
        )
        assert response.status_code == expected


def test_a_missing_token_header_is_422_before_the_service_runs() -> None:
    # Arrange
    service = StubService()

    # Act
    response = _client(service).post(URL, json={"address": "3.228.116.51"})

    # Assert
    assert response.status_code == 422
    assert service.calls == []
