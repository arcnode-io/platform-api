"""Integration test for the per-order ISO bake: real xorriso, real S3 API
(LocalStack), a tiny real base ISO."""

import asyncio
from pathlib import Path

import httpx
import yaml

from src.aws.s3_service import S3Service
from src.iso.iso_service import IsoService
from src.wizard.order_record import OrderSite
from src.wizard.site_fixtures import TEST_ORDER
from tests.fixtures.containers import start_localstack
from tests.fixtures.iso import extract, seed_base_iso

BUCKET = "platform-api-artifacts-test"
ORDER_ID = "6f1c2a9e-0000-4000-8000-000000000042"


def test_bake_adds_the_order_to_the_base_iso(tmp_path: Path) -> None:
    # Arrange
    site = OrderSite(
        site_id="alpha", market_region="ercot", settlement_point="HB_NORTH"
    )
    with start_localstack(services=("s3",)) as ls:
        base_iso_url = seed_base_iso(ls.url, BUCKET, tmp_path)
        s3 = S3Service(endpoint_url=ls.url, bucket=BUCKET)
        # The order's DTM, where the orchestrator archives it.
        dtm = (TEST_ORDER / "dtm.json").read_text()
        asyncio.run(s3.upload_json(f"orders/{ORDER_ID}/dtm.json", dtm))
        service = IsoService(base_iso_url=base_iso_url, s3=s3)

        # Act
        baked = asyncio.run(service.bake(order_id=ORDER_ID, site=site))
        downloaded = tmp_path / "downloaded.iso"
        downloaded.write_bytes(httpx.get(baked.url).raise_for_status().content)

    # Assert
    out = tmp_path / "extracted"
    extract(downloaded, out, "/order", "/preseed.cfg")
    assert yaml.safe_load((out / "order" / "site.yml").read_text()) == site.model_dump()
    assert (out / "order" / "dtm.json").read_text() == dtm
    assert (out / "preseed.cfg").exists()
    assert baked.size_bytes == downloaded.stat().st_size
