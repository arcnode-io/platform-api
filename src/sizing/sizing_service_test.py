"""Unit tests for `SizingService` — verbatim proxy, no real edp-api needed.

Uses `httpx.MockTransport` (part of httpx's own public API, no new
dependency) injected via the constructor to fake edp-api's responses. The
heavier end-to-end proxy path (real edp-api container) is covered in
tests/test_sizing_integration.py.
"""

import httpx
import pytest

from src.sizing.sizing_service import SizingService

BASE_URL = "http://edp-api.example"


@pytest.mark.asyncio
async def test_preview_forwards_body_verbatim_and_relays_200() -> None:
    """Body in = body out; edp-api's 200 + JSON body pass through unchanged."""
    # Arrange
    request_body = b'{"gpu_variant":"h100_sxm","target_gpu_count":64}'
    received: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = request.read()
        received["path"] = request.url.path.encode()
        return httpx.Response(200, json={"site_peak_mw": 4.16})

    service = SizingService(base_url=BASE_URL, transport=httpx.MockTransport(handler))

    # Act
    response = await service.preview(request_body)

    # Assert — exact body forwarded, right upstream path, response relayed
    assert received["body"] == request_body
    assert received["path"] == b"/edp-api/sizing/preview"
    assert response.status_code == 200
    assert response.json() == {"site_peak_mw": 4.16}


@pytest.mark.asyncio
async def test_preview_relays_422_body_unchanged() -> None:
    """edp-api's validation failure relays through as-is — no reinterpretation."""
    # Arrange
    error_body = {"detail": [{"type": "missing", "loc": ["body", "gpu_variant"]}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json=error_body)

    service = SizingService(base_url=BASE_URL, transport=httpx.MockTransport(handler))

    # Act
    response = await service.preview(b"{}")

    # Assert
    assert response.status_code == 422
    assert response.json() == error_body
