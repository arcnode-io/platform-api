"""The order endpoint refuses a client over its limit with 429 and a Retry-After in seconds."""

from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.orders.configurator_payload_test import JS_PAYLOAD
from src.orders.order_rate_limit import OrderRateLimiter
from src.orders.orders_controller import OrdersController
from src.orders.orders_service import OrdersService
from src.orders.orders_record import PostOrderResponse


class StubOrdersService:
    async def submit(self, _payload: object) -> tuple[PostOrderResponse, object]:
        response = PostOrderResponse(
            order_id="6f1c2a9e-0000-4000-8000-000000000042",
            status_url="/platform-api/orders/6f1c2a9e-0000-4000-8000-000000000042",
            submitted_at="2026-10-12T00:00:00+00:00",
        )
        return response, SimpleNamespace(id="6f1c2a9e-0000-4000-8000-000000000042")

    async def execute(self, _order_id: str) -> None:
        return None


def _client(count: int) -> TestClient:
    app = FastAPI()
    controller = OrdersController(
        service=cast(OrdersService, StubOrdersService()),
        limiter=OrderRateLimiter(count=count, window_s=600),
    )
    app.include_router(controller.router)
    return TestClient(app)


def test_the_order_over_the_limit_is_refused_with_retry_after_in_seconds() -> None:
    # Arrange
    client = _client(count=1)

    # Act
    first = client.post("/platform-api/orders", json=JS_PAYLOAD)
    second = client.post("/platform-api/orders", json=JS_PAYLOAD)

    # Assert
    assert first.status_code == 202
    assert second.status_code == 429
    retry = second.headers["retry-after"]
    assert retry.isdigit() and 1 <= int(retry) <= 600
