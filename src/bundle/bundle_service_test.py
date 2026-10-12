"""Unit tests for BundleService — zips an order's manifest files into one arcnode.zip."""

import io
import zipfile
from pathlib import Path

import pytest

from src.aws.s3_service import S3Service
from src.bundle.bundle_record import BundleFile
from src.bundle.bundle_service import BundleService, bundle_files_for
from src.manifest.manifest_record import ManifestArtifact, ManifestFile, ManifestSection


class FakeBundleS3(S3Service):
    """S3Service stand-in: serves bytes per source URL and records the upload."""

    def __init__(self, sources: dict[str, bytes]) -> None:
        self._sources = sources
        self.uploaded_key: str | None = None
        self.uploaded_zip: bytes = b""
        self.uploaded_content_type: str | None = None

    async def download_to(self, url: str, path: Path) -> None:
        path.write_bytes(self._sources[url])

    async def upload_file(self, key: str, path: Path, content_type: str) -> int:
        self.uploaded_key = key
        self.uploaded_zip = path.read_bytes()
        self.uploaded_content_type = content_type
        return len(self.uploaded_zip)


@pytest.mark.asyncio
async def test_build_zips_each_file_under_its_path() -> None:
    # Arrange
    s3 = FakeBundleS3({"s3://b/dtm.json": b'{"devices": []}'})
    service = BundleService(s3=s3)
    files = [BundleFile(path="D1/dtm.json", url="s3://b/dtm.json")]

    # Act
    size = await service.build(order_id="abc123", files=files)

    # Assert
    assert s3.uploaded_key == "orders/abc123/arcnode.zip"
    assert s3.uploaded_content_type == "application/zip"
    assert size == len(s3.uploaded_zip)
    with zipfile.ZipFile(io.BytesIO(s3.uploaded_zip)) as archive:
        assert archive.namelist() == ["D1/dtm.json"]
        assert archive.read("D1/dtm.json") == b'{"devices": []}'


def test_bundle_files_nest_each_file_under_its_artifact_code() -> None:
    """Every manifest file lands at `<artifact code>/<file name>` in the zip."""
    # Arrange
    sections = {
        ManifestSection.SYSTEM_IMAGES: [
            ManifestArtifact(
                code="A1",
                name="Field client",
                subtitle=None,
                files=[
                    ManifestFile(format="APK", size_bytes=1, url="https://h/app.apk")
                ],
            )
        ],
        ManifestSection.ENGINEERING_DRAWINGS: [
            ManifestArtifact(
                code="D1",
                name="DTM",
                subtitle=None,
                files=[
                    ManifestFile(
                        format="JSON",
                        size_bytes=1,
                        url="s3://bucket/orders/x/dtm.json?X-Amz-Signature=abc",
                    )
                ],
            )
        ],
    }

    # Act
    files = bundle_files_for(sections)

    # Assert
    assert files == [
        BundleFile(path="A1/app.apk", url="https://h/app.apk"),
        BundleFile(
            path="D1/dtm.json",
            url="s3://bucket/orders/x/dtm.json?X-Amz-Signature=abc",
        ),
    ]


def test_bundle_files_keep_same_named_files_in_one_artifact_apart() -> None:
    """Two plates with the same file name must not collide inside the zip."""
    # Arrange
    sections = {
        ManifestSection.ENGINEERING_DRAWINGS: [
            ManifestArtifact(
                code="D3",
                name="Plates",
                subtitle=None,
                files=[
                    ManifestFile(
                        format="DXF", size_bytes=1, url="https://h/a/plate.dxf"
                    ),
                    ManifestFile(
                        format="DXF", size_bytes=1, url="https://h/b/plate.dxf"
                    ),
                ],
            )
        ]
    }

    # Act
    files = bundle_files_for(sections)

    # Assert
    assert [f.path for f in files] == ["D3/plate.dxf", "D3/plate-2.dxf"]
