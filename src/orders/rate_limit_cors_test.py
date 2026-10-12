"""The 429 the site relies on carries Retry-After and exposes it to the browser."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.orders.configurator_payload_test import JS_PAYLOAD
from src.orders.order_rate_limit import OrderRateLimiter
from src.orders.orders_controller_test import StubOrdersService
from src.orders.orders_controller import OrdersController
from src.orders.orders_service import OrdersService
from typing import cast


def test_a_cross_origin_429_carries_retry_after_and_exposes_it() -> None:
    # Arrange — the same CORS settings as the app
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://arcnode.io"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
    )
    controller = OrdersController(
        service=cast(OrdersService, StubOrdersService()),
        limiter=OrderRateLimiter(count=1, window_s=600),
    )
    app.include_router(controller.router)
    client = TestClient(app)
    origin = {"Origin": "https://arcnode.io"}

    # Act
    client.post("/platform-api/orders", json=JS_PAYLOAD, headers=origin)
    refused = client.post("/platform-api/orders", json=JS_PAYLOAD, headers=origin)

    # Assert
    assert refused.status_code == 429
    assert refused.headers["retry-after"].isdigit()
    assert "Retry-After" in refused.headers.get("access-control-expose-headers", "")
