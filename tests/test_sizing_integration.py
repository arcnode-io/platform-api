"""Integration test for the sizing/preview proxy.

One real Docker container — edp-api. Unlike test_orders_integration.py,
no postgres/LocalStack needed: /platform-api/sizing/preview never touches
the DB or S3, it's a pure verbatim proxy (CONTRACT §4.3), so this test
skips `register_database()` entirely (no-DB app, per its own docstring).
"""

from ipaddress import IPv4Address

from fastapi.testclient import TestClient

from src.app_module import AppModule
from src.config import Config, LogLevel
from tests.fixtures.containers import start_edp_api

APK_URL: str = "https://f-droid.example/test/ems-hmi.apk"
GATEWAY_TARBALL_URL: str = "https://arcnode-public.example/gateway/latest.tar.gz"

# The 6 required fields of SizingPreviewRequest (CONTRACT §4.2) — verified
# against the live edp-api image's /openapi.json; `grid` is fully optional
# (SizingGridInput has no required fields), so it's left out here.
VALID_REQUEST: dict[str, object] = {
    "gpu_variant": "h100_sxm",
    "target_gpu_count": 64,
    "bess_coupling": "ac_coupled",
    "bess_capacity_mwh": 10.0,
    "deployment_context": "commercial",
    "onsite_generation": {"type": "none", "capacity_mw": None},
}


def _client(edp_api_url: str) -> TestClient:
    cfg = Config(
        log_level=LogLevel.DEBUG,
        port=8000,
        host=IPv4Address("127.0.0.1"),
        e2e=True,
        reload=False,
        postgres_host="localhost",
        postgres_port=5432,
        edp_api_url=edp_api_url,
        s3_endpoint_url="http://localstack.invalid",
        s3_bucket="unused",
        ses_endpoint_url="http://localstack.invalid",
        ses_sender_email="noreply@arcnode.test",
        ems_hmi_apk_url=APK_URL,
        ems_industrial_gateway_tarball_url=GATEWAY_TARBALL_URL,
        iso_version="1.0.0-beta",
        cors_origins=["*"],
    )
    module = AppModule(config=cfg)
    # No register_database() — sizing/preview never touches the DB.
    return TestClient(module.create_app())


def test_sizing_preview_relays_200_shape() -> None:
    """A valid request gets edp-api's real SizingPreview shape back verbatim."""
    with start_edp_api() as edp:
        client = _client(edp.url)

        # Act
        r = client.post("/platform-api/sizing/preview", json=VALID_REQUEST)

        # Assert — relayed status + edp-api's actual response fields present
        assert r.status_code == 200, r.text
        body = r.json()
        assert "site_peak_mw" in body
        assert "grid_peak_mw" in body
        assert "interconnection_level" in body
        assert "limit_state" in body
        assert "flags" in body


def test_sizing_preview_relays_422_on_invalid_request() -> None:
    """edp-api's validation failure relays through unchanged — no reinterpretation."""
    with start_edp_api() as edp:
        client = _client(edp.url)

        # Act — missing every required field
        r = client.post("/platform-api/sizing/preview", json={})

        # Assert
        assert r.status_code == 422, r.text
        assert "detail" in r.json()
