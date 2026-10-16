"""Order fidelity: the delivered BOM says what the customer ordered.

Agreed with power-engineer (2026-10-16) as the platform-api acceptance case
for the 8x H100 / 1 MWh / AC-coupled order:
1. the GPU node line names the ordered GPU variant
2. the customer-supplied BESS line names the ordered capacity and coupling

Container counts are not compared: the sizing preview carries none, and
edp-api's own tests already hold BOM, DTM and drawings coherent with each
other. Same container stack as tests/test_orders_integration.py.
"""

from ipaddress import IPv4Address
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from testcontainers.core.network import Network

from src.app_module import AppModule
from src.config import Config, EmailProvider, LogLevel
from src.edp_client.edp_artifacts import ArtifactKind
from src.orders.configurator_payload import BessCoupling, GpuVariant
from tests.fixtures.containers import (
    seed_edp_manifest,
    start_edp_api,
    start_localstack,
    start_postgres,
)
from tests.fixtures.iso import seed_base_iso
from tests.fixtures.public_downloads import seed_public_downloads
from tests.test_orders_integration import (
    ASSETS_DIR,
    EDP_MANIFEST_PATH,
    POSTGRES_PASSWORD,
    S3_BUCKET,
    SENDER_EMAIL,
    VALID_PAYLOAD,
    _poll_until_complete,
)

# The live run that set this case: order 72e92cb2 on platform.arcnode.io.
FIDELITY_PAYLOAD: dict[str, object] = {
    **VALID_PAYLOAD,
    "deployment_site_name": "pe-fidelity-8xh100-1mwh",
    "gpu_variant": "h100_sxm",
    "target_gpu_count": 8,
    "bess_coupling": "ac_coupled",
    "bess_capacity_mwh": 1.0,
}

# How edp-api spells each ordered choice in a BOM description (seen on order 72e92cb2).
# Reason: only the agreed case is mapped; the DC couplings' wording is unverified.
GPU_MARKER: dict[GpuVariant, str] = {GpuVariant.H100_SXM: "H100"}
COUPLING_MARKER: dict[BessCoupling, str] = {BessCoupling.AC_COUPLED: "AC-coupled"}
BESS_VENDOR: str = "Customer"


class BomLineItem(BaseModel):
    """The BOM fields the fidelity checks read; edp-api owns the full schema."""

    part_number: str
    vendor: str
    description: str
    qty: int


class Bom(BaseModel):
    """bom.json as archived by the orchestrator (fields this test reads)."""

    compute_container_qty: int
    grid_container_qty: int
    line_items: list[BomLineItem]


def _gpu_node_lines(bom: Bom) -> list[BomLineItem]:
    """Server node lines. Reason: the rack row also says "HGX", so key on "GPU server"."""
    return [li for li in bom.line_items if "GPU server" in li.description]


def _bess_lines(bom: Bom) -> list[BomLineItem]:
    """The customer-supplied BESS line (ADR-016: platform never picks the BESS)."""
    return [li for li in bom.line_items if li.vendor == BESS_VENDOR]


def test_the_delivered_bom_names_the_ordered_gpu_and_bess(tmp_path: Path) -> None:
    """8x H100 SXM + 1 MWh AC-coupled in, H100 nodes + a 1 MWh AC-coupled BESS line out."""
    with (
        Network() as net,
        start_postgres(password=POSTGRES_PASSWORD) as pg,
        start_localstack(network=net, network_alias="localstack") as ls,
    ):
        seed_edp_manifest(ls.url, EDP_MANIFEST_PATH, ASSETS_DIR)
        base_iso_url = seed_base_iso(ls.url, S3_BUCKET, tmp_path)
        apk_url, gateway_url = seed_public_downloads(ls.url, S3_BUCKET)
        with (
            start_edp_api(network=net, s3_endpoint_url="http://localstack:4566") as edp,
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
                email_provider=EmailProvider.SES,
                site_dns=False,
                platform_public_url="http://localhost:8000",
                order_rate_limit_count=1000,
                order_rate_limit_window_s=600,
                dns_api_user="test",
                dns_client_ip="127.0.0.1",
                ems_hmi_apk_url=apk_url,
                ems_industrial_gateway_tarball_url=gateway_url,
                base_iso_url=base_iso_url,
                cors_origins=["*"],
            )
            module = AppModule(config=cfg)
            module.register_database()
            app = module.create_app()

            # Arrange — one completed order
            with TestClient(app) as client:
                submit = client.post("/platform-api/orders", json=FIDELITY_PAYLOAD)
                assert submit.status_code == 202, submit.text
                final = _poll_until_complete(client, submit.json()["order_id"])
            assert final.status.value == "complete"

            # Act — read the archived BOM
            bom_ref = next(
                a
                for a in final.edp_artifacts
                if a.kind == ArtifactKind.BOM and a.format == "json"
            )
            bom = Bom.model_validate(httpx.get(bom_ref.url).raise_for_status().json())

            # Assert — the GPU node line is the ordered variant, and only that variant
            gpu_variant = GpuVariant(str(FIDELITY_PAYLOAD["gpu_variant"]))
            nodes = _gpu_node_lines(bom)
            assert len(nodes) == 1, [li.part_number for li in nodes]
            assert GPU_MARKER[gpu_variant] in nodes[0].description, nodes[0]
            assert bom.compute_container_qty == 1

            # Assert — the BESS line is customer-supplied at the ordered size and coupling
            coupling = BessCoupling(str(FIDELITY_PAYLOAD["bess_coupling"]))
            capacity_mwh = float(str(FIDELITY_PAYLOAD["bess_capacity_mwh"]))
            bess = _bess_lines(bom)
            assert len(bess) == 1, [li.description for li in bess]
            assert f"{capacity_mwh:g} MWh" in bess[0].description, bess[0]
            assert COUPLING_MARKER[coupling] in bess[0].description, bess[0]
