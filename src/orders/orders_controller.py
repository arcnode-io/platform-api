"""Orders HTTP controller — POST + GET /platform-api/orders."""

from classy_fastapi import Routable, get, post
from fastapi import BackgroundTasks, HTTPException, status

from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.orders_record import GetOrderResponse, PostOrderResponse
from src.orders.orders_service import OrdersService


class OrdersController(Routable):
    """Async order lifecycle endpoints."""

    def __init__(self, service: OrdersService) -> None:
        super().__init__()
        self._service = service

    @post(
        "/platform-api/orders",
        response_model=PostOrderResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Orders"],
        summary="Submit a configurator payload, kick off the order pipeline",
    )
    async def submit_order(
        self,
        payload: ConfiguratorPayload,
        background_tasks: BackgroundTasks,
    ) -> PostOrderResponse:
        """Create a PENDING order, schedule the orchestrator, return the polling URL."""
        response, order = await self._service.submit(payload)
        background_tasks.add_task(self._service.execute, str(order.id))
        return response

    @get(
        "/platform-api/orders/{order_id}",
        response_model=GetOrderResponse,
        tags=["Orders"],
        summary="Poll order status; returns artifacts on completion",
    )
    async def get_order(self, order_id: str) -> GetOrderResponse:
        """Return current order state. 404 if unknown."""
        record = await self._service.get(order_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"order {order_id} not found",
            )
        return record
