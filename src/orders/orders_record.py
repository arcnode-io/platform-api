"""Pydantic DTOs for the Orders HTTP layer."""

from typing import Optional

from pydantic import BaseModel

from src.edp_client.edp_artifacts import EdpArtifact, EdpDeliveryPath
from src.orders.order_entity import Order, OrderStatus


class OrderEmsDelivery(BaseModel):
    """Platform-api's enriched delivery shape.

    edp-api emits the routing decision (`path` + `ems_mode`); platform-api
    renders a per-order CFN template and exposes its S3 URL as `template_url`.
    Operators download + run it from any partition. ISO path leaves
    `template_url=None` until the v1 ISO build lands.
    """

    path: EdpDeliveryPath
    ems_mode: str
    template_url: Optional[str] = None


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
    ems_delivery: Optional[OrderEmsDelivery] = None
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
                OrderEmsDelivery.model_validate(order.ems_delivery)
                if order.ems_delivery
                else None
            ),
            flags=order.flags,
        )
