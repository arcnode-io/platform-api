"""Unit tests for `ResendService` — the delivery email through Resend's HTTP API.

Uses `httpx.MockTransport` (httpx's own public API) injected via the constructor.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from src.email.resend_service import ResendService

API_KEY = "re_test_key"  # nosec B105 — fake, unit test only
SENDER = "noreply@arcnode.io"


def _service(handler: Callable[[httpx.Request], httpx.Response]) -> ResendService:
    return ResendService(
        api_key=API_KEY, sender_email=SENDER, transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_send_posts_the_email_with_the_bearer_key_and_returns_its_id() -> None:
    # Arrange
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"})

    service = _service(handler)

    # Act
    message_id = await service.send_delivery_email(
        to="ops@acme.io", subject="Your ArcNode EMS is ready", body_text="Links inside."
    )

    # Assert
    assert message_id == "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert seen["body"] == {
        "from": SENDER,
        "to": ["ops@acme.io"],
        "subject": "Your ArcNode EMS is ready",
        "text": "Links inside.",
    }


@pytest.mark.asyncio
async def test_a_rejected_send_raises_with_resends_message() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "statusCode": 403,
                "name": "validation_error",
                "message": "domain is not verified",
            },
        )

    service = _service(handler)

    # Act + Assert
    with pytest.raises(RuntimeError, match="domain is not verified"):
        await service.send_delivery_email(to="ops@acme.io", subject="s", body_text="b")


@pytest.mark.asyncio
async def test_verify_sender_is_a_no_op() -> None:
    """Resend verifies the domain, not an address; the orchestrator calls this for parity with SES."""
    # Arrange
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    service = _service(handler)

    # Act
    await service.verify_sender()

    # Assert
    assert calls == 0
