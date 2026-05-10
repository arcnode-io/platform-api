"""Unit tests for `PortalService.render` + `render_manifest_json`.

Pure renderer. Builds a representative DeploymentManifest in-test and asserts
the rendered HTML carries the design-fidelity content the operator must see.
The manifest schema is exercised separately in src/manifest/manifest_service_test.
"""

import json
from datetime import UTC, datetime

from src.manifest.manifest_record import (
    DeploymentManifest,
    ManifestArtifact,
    ManifestFile,
    ManifestSection,
)
from src.portal.portal_service import (
    PortalService,
    _filesize,
    _split_curl_url,
)

BUILT_AT = datetime(2026, 4, 29, 18, 42, tzinfo=UTC)


def _file(fmt: str, size: int) -> ManifestFile:
    return ManifestFile(format=fmt, size_bytes=size, url=f"https://x/{fmt.lower()}")


def _manifest(*, signed: bool = True, with_bundle: bool = False) -> DeploymentManifest:
    """Representative manifest covering all three sections + chip color families."""
    return DeploymentManifest(
        site_slug="brookside-dc-1",
        site_display_name="Brookside DC-1",
        bundle_id="ARCNODE-EMS-1.0.0",
        revision=3,
        supersedes="ARCNODE-EMS-0.9.2" if signed else None,
        built_at=BUILT_AT,
        signed=signed,
        key_id="0xA3F1...9C72" if signed else None,
        total_size_bytes=2_640_000_000,
        total_file_count=21,
        artifact_count=10,
        bundle_url="https://example.com/orders/x/arcnode.zip" if with_bundle else None,
        bundle_curl_url="https://delivery.arcnode.io/brookside-dc-1/arcnode.zip",
        sections={
            ManifestSection.SYSTEM_IMAGES: [
                ManifestArtifact(
                    code="A1",
                    name="EMS Field Client",
                    subtitle="MOCK Android · arm64-v8a · minSdk 30",
                    files=[_file("APK", 38_400_000), _file("AAB", 34_100_000)],
                ),
            ],
            ManifestSection.ENGINEERING_DRAWINGS: [
                ManifestArtifact(
                    code="D1",
                    name="Single Line Diagram",
                    subtitle="AC + DC distribution to module level",
                    files=[_file("DXF", 1_400_000), _file("PDF", 420_000)],
                ),
            ],
            ManifestSection.MANIFESTS_AND_SCHEDULES: [
                ManifestArtifact(
                    code="M1",
                    name="Bill of Materials",
                    subtitle="MOCK 1,284 items · 47 vendors",
                    files=[_file("JSON", 612_000), _file("XLSX", 288_000)],
                ),
            ],
        },
    )


# ─── Pure helpers ────────────────────────────────────────────────────


def test_filesize_decimal_scaling() -> None:
    """Mockup-matching format: 'B' under 1KB; 'KB'/'MB' 1 decimal; 'GB' 2 decimals.

    Decimal (1000) base for parity with macOS Finder + Windows Explorer.
    """
    # Arrange + Act + Assert
    assert _filesize(128) == "128 B"
    assert _filesize(566) == "566 B"
    assert _filesize(880_000) == "880.0 KB"
    assert _filesize(38_400_000) == "38.4 MB"
    assert _filesize(2_460_000_000) == "2.46 GB"


def test_split_curl_url_separates_filename_for_chip_coloring() -> None:
    """The trailing path segment is colorized in the curl one-liner."""
    # Arrange + Act
    prefix, fname = _split_curl_url(
        "https://delivery.arcnode.io/brookside-dc-1/arcnode.zip"
    )

    # Assert
    assert prefix == "https://delivery.arcnode.io/brookside-dc-1/"
    assert fname == "arcnode.zip"


# ─── Rendered HTML fidelity ──────────────────────────────────────────


def test_render_includes_site_identity_block() -> None:
    """Site display name, bundle id, signed badge all surface in the header."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert "BROOKSIDE DC-1" in html  # uppercased site name
    assert "ARCNODE-EMS-1.0.0" in html
    assert "SIGNED" in html
    assert "0xA3F1...9C72" in html


def test_render_includes_metadata_line() -> None:
    """Rev/supersedes/built-at/file-count/total-size all in the metadata strip."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert "Rev 3" in html
    assert "supersedes ARCNODE-EMS-0.9.2" in html
    assert "29 Apr 2026" in html
    assert "18:42 UTC" in html
    assert "21 files" in html
    assert "10 artifacts" in html


def test_render_marks_mock_data_in_subtitles() -> None:
    """MOCK_-prefixed subtitles in the artifact rows surface every fake-data
    swap point. Visible to operators (intentional 'this is placeholder').
    """
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert "MOCK Android" in html  # System Images subtitle
    assert "MOCK 1,284 items" in html  # BOM subtitle


def test_render_three_columns_with_section_numbers() -> None:
    """Three columns with §01/§02/§03 numbering + headers from SECTION_LABEL."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    for num in ("§ 01", "§ 02", "§ 03"):
        assert num in html
    assert "System Images" in html
    assert "Engineering Drawings" in html
    assert "Manifests &amp; Schedules" in html  # & is HTML-escaped


def test_render_artifacts_with_letter_codes_and_subtitles() -> None:
    """Each artifact shows its code (A1, D1, M1) + name + subtitle."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    for code, name in [
        ("A1", "EMS Field Client"),
        ("D1", "Single Line Diagram"),
        ("M1", "Bill of Materials"),
    ]:
        assert code in html
        assert name in html
    assert "AC + DC distribution to module level" in html


def test_render_file_chips_with_format_and_size() -> None:
    """Each file becomes a chip showing format + human-readable size."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert — sample chips across the three families
    assert "APK" in html
    assert "DXF" in html
    assert "JSON" in html
    assert "38.4 MB" in html  # APK 38_400_000 bytes
    assert "1.4 MB" in html  # DXF 1_400_000 bytes
    assert "612.0 KB" in html  # JSON 612_000 bytes


def test_render_chip_classes_drive_color_coding() -> None:
    """Format-based CSS class hooks the per-family color palette."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert 'class="chip chip-apk"' in html
    assert 'class="chip chip-dxf"' in html
    assert 'class="chip chip-json"' in html


def test_render_curl_one_liner_with_highlighted_filename() -> None:
    """Curl command shown with the trailing arcnode.zip wrapped for color."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert (
        "curl -LO https://delivery.arcnode.io/brookside-dc-1/"
        '<span class="filename">arcnode.zip</span>'
    ) in html


def test_render_bundle_pending_when_no_bundle_url() -> None:
    """Phase 1 has no bundle yet — show the disabled placeholder CTA."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest(with_bundle=False))

    # Assert
    assert "BUNDLE PENDING" in html
    assert "DOWNLOAD BUNDLE" not in html


def test_render_download_bundle_when_url_present() -> None:
    """Once Phase 2 lands a bundle_url, the primary CTA goes live."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest(with_bundle=True))

    # Assert
    assert "DOWNLOAD BUNDLE" in html
    assert "BUNDLE PENDING" not in html
    assert "arcnode.zip" in html


def test_render_drops_signed_badge_when_unsigned() -> None:
    """Unsigned bundles skip the SIGNED badge entirely."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest(signed=False))

    # Assert — badge not shown, key not in metadata
    assert "SIGNED" not in html


def test_render_footer_pre_signed_url_notice() -> None:
    """Footer states the 7-day expiration policy on pre-signed URLs."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert "Pre-signed URLs" in html
    assert "expire 7 days" in html


def test_render_loads_required_fonts() -> None:
    """Bebas Neue + DM Mono come from Google Fonts (sovereign theme)."""
    # Arrange + Act
    html = PortalService().render(manifest=_manifest())

    # Assert
    assert "fonts.googleapis.com" in html
    assert "Bebas+Neue" in html
    assert "DM+Mono" in html


# ─── manifest.json output ────────────────────────────────────────────


def test_render_manifest_json_round_trips_through_pydantic() -> None:
    """The rendered JSON re-parses into a DeploymentManifest unchanged."""
    # Arrange
    m = _manifest()
    svc = PortalService()

    # Act
    raw = svc.render_manifest_json(manifest=m)
    parsed = DeploymentManifest.model_validate(json.loads(raw))

    # Assert — round-trip identity
    assert parsed.site_slug == m.site_slug
    assert parsed.bundle_id == m.bundle_id
    assert parsed.total_file_count == m.total_file_count
    assert (
        parsed.sections[ManifestSection.SYSTEM_IMAGES][0].code
        == m.sections[ManifestSection.SYSTEM_IMAGES][0].code
    )


def test_render_manifest_json_is_pretty_printed() -> None:
    """Two-space indent for readability when an operator opens manifest.json."""
    # Arrange + Act
    raw = PortalService().render_manifest_json(manifest=_manifest())

    # Assert — at least one indented line
    assert '\n  "' in raw
