"""OrdersService — submit + execute + get.

Mirrors edp-api's JobsService shape: POST creates an Order row, schedules a
BackgroundTask running `OrchestratorService.execute`, returns the 202 body.
GET reads the row.
"""

import logging
import uuid
from datetime import UTC, datetime

from src.orchestrator.orchestrator_service import OrchestratorService
from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.order_entity import Order, OrderStatus
from src.orders.orders_record import (
    GetOrderResponse,
    PostOrderResponse,
    order_to_response,
)


class OrdersService:
    """Order lifecycle: create → schedule → update on completion."""

    def __init__(self, *, orchestrator: OrchestratorService) -> None:
        self._orchestrator = orchestrator

    async def submit(
        self, payload: ConfiguratorPayload
    ) -> tuple[PostOrderResponse, Order]:
        """Persist a PENDING order and return the 202 body. Caller schedules execute."""
        order = await Order.create(
            id=uuid.uuid4(),
            status=OrderStatus.PENDING,
            submitted_at=datetime.now(UTC),
            payload=payload.model_dump(mode="json"),
        )
        logging.info("order submitted: %s", order.id)
        return (
            PostOrderResponse(
                order_id=str(order.id),
                status_url=f"/platform-api/orders/{order.id}",
                submitted_at=order.submitted_at.isoformat(),
            ),
            order,
        )

    async def execute(self, order_id: str) -> None:
        """BackgroundTask entry point — runs the orchestrator for one order."""
        order = await Order.get_or_none(id=order_id)
        if order is None:
            logging.error("order %s missing at execute time", order_id)
            return
        await self._orchestrator.execute(order)

    async def get(self, order_id: str) -> GetOrderResponse | None:
        """Read one order by id; None if unknown."""
        order = await Order.get_or_none(id=order_id)
        return order_to_response(order) if order else None
