"""Integration test for the full order orchestrator flow.

Three real Docker containers backing this test (session-scoped):
- postgres        — Tortoise ORM persistence
- localstack      — fake AWS S3 + SES (real boto3 API)
- edp-api:test    — the published edp-api image; same one platform-api hits in prod

Walks the walking-skeleton path:
1. POST /platform-api/orders → 202 with order_id
2. GET /platform-api/orders/{id} polled until status == "complete"
3. Artifact bytes archived to platform-api's S3 bucket (re-archived FROM edp-api)
4. SES captured a single delivery email to the operator's contact_email
"""

import time
from collections.abc import Generator

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient

from src.app_module import AppModule
from src.config import Config
from src.orders.orders_record import GetOrderResponse
from tests.fixtures.containers import Container

VALID_PAYLOAD: dict[str, object] = {
    "operator_org": "acme",
    "deployment_site_name": "alpha",
    "contact_email": "ops@acme.test",
    "energy_source": "nuclear",
    "source_capacity_mw": 10.0,
    "primary_workload": "ai_training",
    "gpu_variant": "h100_sxm",
    "target_gpu_count": 64,
    "bess_autonomy_hr": 2.0,
    "grid_connection": "grid_tied",
    "climate_zone": "temperate",
    "deployment_context": "commercial",
    "ems_mode": "sim",
    "aws_partition": "standard",
}

POLL_TIMEOUT_SECONDS: float = 60.0
POLL_INTERVAL_SECONDS: float = 0.5


@pytest.fixture(scope="session")
def app_client(integration_config: Config) -> Generator[TestClient]:
    """Build the platform-api app pointed at all three containers."""
    module = AppModule(config=integration_config)
    module.register_database()
    app = module.create_app()
    # Reason: TestClient's __enter__ fires the FastAPI lifespan (Tortoise init).
    with TestClient(app) as client:
        yield client


def _poll_until_complete(client: TestClient, order_id: str) -> GetOrderResponse:
    """Poll GET /platform-api/orders/{id} until status reaches a terminal state."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        r = client.get(f"/platform-api/orders/{order_id}")
        assert r.status_code == 200, r.text
        body = GetOrderResponse.model_validate(r.json())
        if body.status.value in ("complete", "failed"):
            return body
        time.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(
        f"order {order_id} did not reach terminal state in {POLL_TIMEOUT_SECONDS}s"
    )


def test_order_full_pipeline_archives_artifacts_and_sends_email(
    app_client: TestClient,
    localstack: Container,
    integration_config: Config,
) -> None:
    """POST → poll → assert S3 bytes + SES email captured."""
    # Act — submit order
    submit = app_client.post("/platform-api/orders", json=VALID_PAYLOAD)
    assert submit.status_code == 202, submit.text
    order_id = submit.json()["order_id"]

    # Act — poll until complete
    final = _poll_until_complete(app_client, order_id)

    # Assert — order completed with re-archived platform-api S3 URLs
    assert final.status.value == "complete"
    artifact_names = {a.name for a in final.edp_artifacts}
    assert "Bill of Materials" in artifact_names
    assert "Device Topology Manifest" in artifact_names
    bom = next(a for a in final.edp_artifacts if a.name == "Bill of Materials")
    bom_url = bom.urls[0].url
    assert bom_url is not None
    assert (
        localstack.url in bom_url
    ), f"expected platform-api to re-archive into LocalStack S3; got {bom_url}"

    # Assert — bytes actually landed in the bucket
    s3 = boto3.client(
        "s3",
        endpoint_url=integration_config.s3_endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106
    )
    objs = s3.list_objects_v2(Bucket=integration_config.s3_bucket)
    keys = {o["Key"] for o in objs.get("Contents", [])}
    assert any(k.endswith("bom.json") for k in keys), keys
    assert any(k.endswith("dtm.json") for k in keys), keys
    assert any(k.endswith("cable_hose_schedule.json") for k in keys), keys

    # Assert — SES received the delivery email.
    # LocalStack SES exposes sent emails via the internal `_aws/ses` endpoint
    sent = httpx.get(f"{integration_config.ses_endpoint_url}/_aws/ses").json()
    messages = sent.get("messages", [])
    delivery_emails = [
        m
        for m in messages
        if VALID_PAYLOAD["contact_email"]
        in m.get("Destination", {}).get("ToAddresses", [])
    ]
    assert (
        len(delivery_emails) == 1
    ), f"expected one delivery email; got {len(delivery_emails)}: {messages}"
