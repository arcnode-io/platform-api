"""Integration test for the full order orchestrator flow.

Three real Docker containers backing this test (started inline as context
managers — no pytest fixtures, just `with` blocks):
- postgres        — Tortoise ORM persistence
- localstack      — fake AWS S3 + SES (real boto3 API)
- edp-api:test    — the published edp-api image; same one platform-api hits in prod

Walks the walking-skeleton path:
1. POST /platform-api/orders → 202 with order_id
2. GET /platform-api/orders/{id} polled until status == "complete"
3. Artifact bytes archived to platform-api's S3 bucket (re-archived FROM edp-api)
4. SES captured a single delivery email to the operator's contact_email
5. Email body advertises the EMS HMI Android APK URL
"""

import time
from ipaddress import IPv4Address

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient

from src.app_module import AppModule
from src.config import Config, LogLevel
from src.orders.orders_record import GetOrderResponse
from tests.fixtures.containers import (
    start_edp_api,
    start_localstack,
    start_postgres,
)

POSTGRES_PASSWORD: str = "test"  # noqa: S105 — testcontainer credential
S3_BUCKET: str = "platform-api-artifacts-test"
APK_URL: str = "https://f-droid.example/test/ems-hmi.apk"
SENDER_EMAIL: str = "noreply@arcnode.test"

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


def test_order_full_pipeline_archives_artifacts_and_sends_email() -> None:
    """POST → poll → assert S3 bytes + SES email captured + APK link in body."""
    with (
        start_postgres(password=POSTGRES_PASSWORD) as pg,
        start_localstack() as ls,
        start_edp_api() as edp,
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)
        cfg = Config(
            log_level=LogLevel.DEBUG,
            port=8000,
            host=IPv4Address("127.0.0.1"),
            e2e=True,
            reload=False,
            postgres_host="localhost",
            postgres_port=pg.port,
            edp_api_url=edp.url,
            s3_endpoint_url=ls.url,
            s3_bucket=S3_BUCKET,
            ses_endpoint_url=ls.url,
            ses_sender_email=SENDER_EMAIL,
            ems_hmi_apk_url=APK_URL,
        )
        module = AppModule(config=cfg)
        module.register_database()
        app = module.create_app()

        with TestClient(app) as client:
            # Act — submit order
            submit = client.post("/platform-api/orders", json=VALID_PAYLOAD)
            assert submit.status_code == 202, submit.text
            order_id = submit.json()["order_id"]

            # Act — poll until complete
            final = _poll_until_complete(client, order_id)

        # Assert — order completed with re-archived platform-api S3 URLs
        assert final.status.value == "complete"
        artifact_names = {a.name for a in final.edp_artifacts}
        assert "Bill of Materials" in artifact_names
        assert "Device Topology Manifest" in artifact_names
        bom = next(a for a in final.edp_artifacts if a.name == "Bill of Materials")
        bom_url = bom.urls[0].url
        assert bom_url is not None
        assert ls.url in bom_url, (
            f"expected platform-api to re-archive into LocalStack S3; got {bom_url}"
        )

        # Assert — bytes actually landed in the bucket
        s3 = boto3.client(
            "s3",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",  # noqa: S106 — LocalStack
            aws_secret_access_key="test",  # noqa: S106
        )
        objs = s3.list_objects_v2(Bucket=S3_BUCKET)
        keys = {o["Key"] for o in objs.get("Contents", [])}
        assert any(k.endswith("bom.json") for k in keys), keys
        assert any(k.endswith("dtm.json") for k in keys), keys
        assert any(k.endswith("cable_hose_schedule.json") for k in keys), keys

        # Assert — SES received the delivery email + email body advertises the APK URL
        sent = httpx.get(f"{ls.url}/_aws/ses").json()
        delivery_emails = [
            m
            for m in sent.get("messages", [])
            if VALID_PAYLOAD["contact_email"]
            in m.get("Destination", {}).get("ToAddresses", [])
        ]
        assert len(delivery_emails) == 1, (
            f"expected one delivery email; got {len(delivery_emails)}"
        )
        body = delivery_emails[0].get("Body", {}).get("text_part", "")
        assert APK_URL in body, f"expected APK URL in email body; got: {body!r}"
