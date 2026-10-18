"""Tests for `ManifestService.build` — pure composition, no I/O."""

from datetime import UTC, datetime

from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef
from src.manifest.manifest_record import (
    ManifestArtifact,
    ManifestFile,
    ManifestSection,
)
from src.manifest.manifest_service import ManifestService

BUILT_AT: datetime = datetime(2026, 4, 29, 18, 42, tzinfo=UTC)
BUNDLE_URL: str = "https://bucket.s3.amazonaws.com/orders/x/arcnode.zip"


def _service() -> ManifestService:
    return ManifestService()


def _ref(kind: ArtifactKind, fmt: str, size: int = 1000) -> tuple[ArtifactRef, int]:
    return (
        ArtifactRef(
            kind=kind,
            format=fmt,
            url=f"https://example.com/{kind.value}.{fmt}",
        ),
        size,
    )


def test_build_slugifies_site_name() -> None:
    """Display name → URL-safe slug (lowercase, dash-separated)."""
    # Arrange + Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="Brookside DC-1",
        archived=[],
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert
    assert m.site_slug == "brookside-dc-1"
    assert m.site_display_name == "Brookside DC-1"


def test_build_assigns_positional_letter_codes_per_section() -> None:
    """A1/A2 for system images, D1..Dn for drawings, M1..Mn for manifests."""
    # Arrange
    archived = [
        _ref(ArtifactKind.BOM, "json", 100),
        _ref(ArtifactKind.SLD, "dxf", 200),
        _ref(ArtifactKind.DTM, "json", 300),
        _ref(ArtifactKind.PID_COOLING, "pdf", 400),
    ]
    apk_artifact = ManifestArtifact(
        code="",
        name="EMS Field Client",
        subtitle="MOCK Android",
        files=[
            ManifestFile(format="APK", size_bytes=40_000_000, url="https://x/y.apk")
        ],
    )

    # Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="Test Site",
        archived=archived,
        system_artifacts=[apk_artifact],
        built_at=BUILT_AT,
    )

    # Assert
    a_codes = [a.code for a in m.sections[ManifestSection.SYSTEM_IMAGES]]
    d_codes = [a.code for a in m.sections[ManifestSection.ENGINEERING_DRAWINGS]]
    m_codes = [a.code for a in m.sections[ManifestSection.MANIFESTS_AND_SCHEDULES]]
    assert a_codes == ["A1"]
    assert d_codes == ["D1", "D2"]
    assert m_codes == ["M1", "M2"]


def test_build_collapses_same_kind_into_one_artifact_with_multiple_files() -> None:
    """Per mockup: SLD with DXF + PDF lands as one row with two chips."""
    # Arrange
    archived = [
        _ref(ArtifactKind.SLD, "dxf", 1_400_000),
        _ref(ArtifactKind.SLD, "pdf", 420_000),
    ]

    # Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="t",
        archived=archived,
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert — single SLD artifact with 2 files
    drawings = m.sections[ManifestSection.ENGINEERING_DRAWINGS]
    assert len(drawings) == 1
    assert drawings[0].name == "Single Line Diagram"
    formats = {f.format for f in drawings[0].files}
    assert formats == {"DXF", "PDF"}


def test_build_computes_totals() -> None:
    """size + file + artifact counts sum across all sections."""
    # Arrange
    archived = [
        _ref(ArtifactKind.BOM, "json", 100),
        _ref(ArtifactKind.BOM, "xlsx", 200),
        _ref(ArtifactKind.DTM, "json", 300),
    ]
    apk = ManifestArtifact(
        code="",
        name="EMS Field Client",
        subtitle="MOCK Android",
        files=[ManifestFile(format="APK", size_bytes=400, url="https://x/y.apk")],
    )

    # Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="t",
        archived=archived,
        system_artifacts=[apk],
        built_at=BUILT_AT,
    )

    # Assert
    assert m.total_size_bytes == 1000  # 100+200+300+400
    assert m.total_file_count == 4  # 2 BOM files + 1 DTM file + 1 APK
    assert m.artifact_count == 3  # BOM, DTM, EMS Field Client


def test_build_reports_unsigned_until_manifest_signing_exists() -> None:
    """No fake signature: the manifest says unsigned and carries no key."""
    # Arrange + Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="t",
        archived=[],
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert
    assert m.signed is False
    assert m.key_id is None


def test_build_puts_the_bundle_url_in_the_header_and_curl_line() -> None:
    """The bundle link is the zip's plain URL, shown as-is."""
    # Arrange + Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="Brookside DC-1",
        archived=[],
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert
    assert m.bundle_url == BUNDLE_URL
    assert m.bundle_curl_url == BUNDLE_URL


def test_build_uppercases_file_formats() -> None:
    """ArtifactRef.format is lowercase ('dxf', 'json'); manifest shows uppercase."""
    # Arrange
    archived = [_ref(ArtifactKind.BOM, "json", 100)]

    # Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="t",
        archived=archived,
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert
    bom = m.sections[ManifestSection.MANIFESTS_AND_SCHEDULES][0]
    assert bom.files[0].format == "JSON"


def test_build_empty_when_no_inputs() -> None:
    """Smoke: zero artifacts yields a manifest with empty sections + 0 totals."""
    # Arrange + Act
    m = _service().build(
        bundle_url=BUNDLE_URL,
        site_display_name="t",
        archived=[],
        system_artifacts=[],
        built_at=BUILT_AT,
    )

    # Assert
    for arts in m.sections.values():
        assert arts == []
    assert m.total_size_bytes == 0
    assert m.total_file_count == 0
    assert m.artifact_count == 0
