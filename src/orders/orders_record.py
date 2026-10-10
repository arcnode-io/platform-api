"""Pydantic DTOs for the Orders HTTP layer."""

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel

from src.edp_client.edp_artifacts import ArtifactRef
from src.orders.configurator_payload import AwsPartition
from src.orders.order_entity import Order, OrderStatus


class DeliveryPath(StrEnum):
    """Platform-api routing decision — derived from `aws_partition`."""

    CFN_STANDARD = "cfn_standard"
    CFN_GOVCLOUD = "cfn_govcloud"
    ISO = "iso"


# Reason: edp-api no longer emits routing — platform-api derives it from the
# customer's AWS partition choice. ISO path covers on-prem (no AWS).
_PARTITION_TO_PATH: dict[AwsPartition, DeliveryPath] = {
    AwsPartition.STANDARD: DeliveryPath.CFN_STANDARD,
    AwsPartition.GOVCLOUD: DeliveryPath.CFN_GOVCLOUD,
    AwsPartition.NONE: DeliveryPath.ISO,
}


def derive_delivery_path(partition: AwsPartition) -> DeliveryPath:
    """1:1 partition -> path mapping."""
    return _PARTITION_TO_PATH[partition]


class OrderEmsDelivery(BaseModel):
    """Platform-api's per-order delivery shape.

    Path derived from `aws_partition`. CFN paths: a per-order CFN template at
    `template_url`. ISO path: the appliance installer with the order baked
    in (src/iso/iso_service.py) at `iso_url`, a 7-day presigned link.
    """

    path: DeliveryPath
    template_url: Optional[str] = None
    iso_url: Optional[str] = None
    iso_size_bytes: Optional[int] = None  # for the portal's chip


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
    edp_artifacts: list[ArtifactRef] = []
    ems_delivery: Optional[OrderEmsDelivery] = None

    @classmethod
    def from_order(cls, order: Order) -> "GetOrderResponse":
        """Project a Tortoise `Order` row onto the public GET-response schema."""
        return cls(
            order_id=str(order.id),
            status=order.status,
            submitted_at=order.submitted_at.isoformat(),
            completed_at=order.completed_at.isoformat() if order.completed_at else None,
            edp_artifacts=[ArtifactRef.model_validate(a) for a in order.edp_artifacts],
            ems_delivery=(
                OrderEmsDelivery.model_validate(order.ems_delivery)
                if order.ems_delivery
                else None
            ),
        )
