"""BundleService — zips one order's manifest files into `orders/<id>/arcnode.zip`."""

import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from typing import Final

from src.aws.s3_service import S3Service
from src.bundle.bundle_record import BundleFile
from src.manifest.manifest_record import ManifestArtifact, ManifestSection

ZIP_CONTENT_TYPE: Final[str] = "application/zip"


class BundleService:
    """Builds the per-order zip on local disk, then uploads it to S3."""

    def __init__(self, *, s3: S3Service) -> None:
        self._s3 = s3

    async def build(self, *, order_id: str, files: list[BundleFile]) -> int:
        """Zip `files` and upload. Returns the zip's size in bytes."""
        with tempfile.TemporaryDirectory() as scratch:
            scratch_dir = Path(scratch)
            zip_path = scratch_dir / "arcnode.zip"
            # Reason: installers are already compressed (ISO, APK), so STORED keeps the build fast.
            with zipfile.ZipFile(
                zip_path, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for index, entry in enumerate(files):
                    source = scratch_dir / str(index)
                    await self._s3.download_to(entry.url, source)
                    archive.write(source, arcname=entry.path)
                    source.unlink()
            return await self._s3.upload_file(
                f"orders/{order_id}/arcnode.zip", zip_path, ZIP_CONTENT_TYPE
            )


def bundle_files_for(
    sections: dict[ManifestSection, list[ManifestArtifact]],
) -> list[BundleFile]:
    """Flatten a manifest's sections into zip entries, one per downloadable file."""
    entries: list[BundleFile] = []
    taken: set[str] = set()
    for arts in sections.values():
        for artifact in arts:
            for file in artifact.files:
                name = urlparse(file.url).path.rsplit("/", 1)[-1]
                path = unique_path(f"{artifact.code}/{name}", taken)
                taken.add(path)
                entries.append(BundleFile(path=path, url=file.url))
    return entries


def unique_path(path: str, taken: set[str]) -> str:
    """`D3/plate.dxf` → `D3/plate-2.dxf` when `D3/plate.dxf` is already in the zip."""
    if path not in taken:
        return path
    posix = PurePosixPath(path)
    count = 2
    while str(posix.with_name(f"{posix.stem}-{count}{posix.suffix}")) in taken:
        count += 1
    return str(posix.with_name(f"{posix.stem}-{count}{posix.suffix}"))
