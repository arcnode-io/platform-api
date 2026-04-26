"""Pydantic DTOs for the Orders HTTP layer."""

from typing import Optional

from pydantic import BaseModel

from src.edp_client.edp_artifacts import EdpArtifact, EdpEmsDelivery
from src.orders.order_entity import Order, OrderStatus


class PostOrderResponse(BaseModel):
    """POST /platform-api/orders 202 body."""

    order_id: str
    status_url: str
    submitted_at: str


class GetOrderResponse(BaseModel):
    """GET /platform-api/orders/{id} body."""

    order_id: str
    status: OrderStatus
    submitted_at: str
    completed_at: Optional[str] = None
    edp_artifacts: list[EdpArtifact] = []
    ems_delivery: Optional[EdpEmsDelivery] = None
    flags: list[dict[str, object]] = []

    @classmethod
    def from_order(cls, order: Order) -> "GetOrderResponse":
        """Project a Tortoise `Order` row onto the public GET-response schema."""
        return cls(
            order_id=str(order.id),
            status=order.status,
            submitted_at=order.submitted_at.isoformat(),
            completed_at=order.completed_at.isoformat() if order.completed_at else None,
            edp_artifacts=[EdpArtifact.model_validate(a) for a in order.edp_artifacts],
            ems_delivery=(
                EdpEmsDelivery.model_validate(order.ems_delivery)
                if order.ems_delivery
                else None
            ),
            flags=order.flags,
        )
