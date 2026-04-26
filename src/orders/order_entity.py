"""Tortoise ORM entity for `Order`. Single table, status enum, JSON columns."""

from enum import StrEnum

from tortoise import Model, fields


class OrderStatus(StrEnum):
    """Order lifecycle. Mirrors edp-api JobStatus closely."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Order(Model):
    """One row per operator submission."""

    id = fields.UUIDField(primary_key=True)
    status = fields.CharEnumField(OrderStatus, default=OrderStatus.PENDING)
    submitted_at = fields.DatetimeField(auto_now_add=True)
    completed_at = fields.DatetimeField(null=True)

    # JSON columns — payload (input), edp_artifacts (output URLs), ems_delivery (routing)
    payload = fields.JSONField()
    edp_job_id = fields.CharField(max_length=64, null=True)
    deployment_uuid = fields.CharField(max_length=64, null=True)
    edp_artifacts = fields.JSONField(default=list)
    ems_delivery = fields.JSONField(null=True)
    flags = fields.JSONField(default=list)

    class Meta:
        table = "orders"
