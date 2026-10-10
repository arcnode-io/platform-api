"""IsoService — bakes an order into the appliance installer: the generic
base ISO (built by src/iso/build.sh, published by CI) plus /order, the
order's site + device topology. The installer copies /order onto the box
and the wizard's Site page hands it to the EMS containers."""

import asyncio
import filecmp
import logging
import tempfile
from pathlib import Path
from typing import Final

import httpx
import yaml
from pydantic import BaseModel

from src.aws.s3_service import S3Service
from src.wizard.order_record import DTM_FILE, SITE_FILE, OrderSite

ISO_CONTENT_TYPE: Final[str] = "application/x-iso9660-image"
# S3's SigV4 maximum. Reason: the ISO holds the order's topology, so it
# can't be public; a never-expiring link needs portal login first.
LINK_SECONDS: Final[int] = 7 * 24 * 3600


class BakedIso(BaseModel):
    """The per-order ISO's download link + size (for the portal's chip)."""

    url: str
    size_bytes: int


class IsoService:
    """Base ISO + /order → orders/{id}/arcnode-ems.iso in our bucket."""

    def __init__(self, *, base_iso_url: str, s3: S3Service) -> None:
        self._base_iso_url = base_iso_url
        self._s3 = s3

    async def bake(self, *, order_id: str, site: OrderSite) -> BakedIso:
        """Add the order's site.yml + its archived dtm.json to the base ISO,
        check they landed, upload it, return a download link."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            base = work / "base.iso"
            await self._download_base(base)
            order = work / "order"
            order.mkdir()
            (order / SITE_FILE).write_text(
                yaml.safe_dump(site.model_dump(), sort_keys=False)
            )
            dtm = await self._s3.get_bytes(f"orders/{order_id}/{DTM_FILE}")
            (order / DTM_FILE).write_bytes(dtm)
            baked = work / "arcnode-ems.iso"
            # Reason: replay keeps the base ISO's BIOS + UEFI boot setup; only
            # /order is added — no Debian rebuild, seconds per order.
            await _xorriso(
                "-indev", str(base), "-outdev", str(baked),
                "-boot_image", "any", "replay",
                "-map", str(order), "/order",
            )  # fmt: skip
            await _check_order(baked, order, work / "check")
            key = f"orders/{order_id}/arcnode-ems.iso"
            size = await self._s3.upload_file(key, baked, ISO_CONTENT_TYPE)
        url = await self._s3.generate_presigned_url(key, LINK_SECONDS)
        logging.info("baked order %s into %s (%d bytes)", order_id, key, size)
        return BakedIso(url=url, size_bytes=size)

    async def _download_base(self, path: Path) -> None:
        """Stream it to disk — ~800 MB, never held in memory."""
        async with (
            httpx.AsyncClient(follow_redirects=True) as http,
            http.stream("GET", self._base_iso_url) as response,
        ):
            response.raise_for_status()
            with path.open("wb") as out:
                async for chunk in response.aiter_bytes():
                    out.write(chunk)


async def _check_order(iso: Path, order: Path, check: Path) -> None:
    """Extract /order back out of the baked ISO; it must match what went in."""
    await _xorriso(
        "-osirrox", "on", "-indev", str(iso), "-extract", "/order", str(check)
    )
    for name in (SITE_FILE, DTM_FILE):
        if not filecmp.cmp(order / name, check / name, shallow=False):
            raise RuntimeError(f"baked ISO's /order/{name} differs from the order's")


async def _xorriso(*args: str) -> None:
    """Run xorriso; fail with its own output."""
    process = await asyncio.create_subprocess_exec(
        "xorriso",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"xorriso failed: {output.decode()[-2000:]}")
