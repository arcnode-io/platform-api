"""Unit tests for orchestrator_service helpers."""

import pytest

from src.orchestrator.orchestrator_service import _slugify_site_id


class TestSlugifySiteId:
    """ASCII snake_case slug — operator names are user-supplied free-form text."""

    def test_simple_ascii_becomes_snake_case(self) -> None:
        assert _slugify_site_id("Nevada Facility 2") == "nevada_facility_2"

    def test_dashes_collapse_to_underscores(self) -> None:
        assert _slugify_site_id("Brookside DC-1") == "brookside_dc_1"

    def test_accented_chars_stripped(self) -> None:
        # 'é' is unicode-alnum but not ASCII; must be stripped.
        assert _slugify_site_id("Café 🔥 Site") == "caf_site"

    def test_pure_emoji_raises(self) -> None:
        # All-stripped input would write empty site_id to MQTT — refuse it.
        with pytest.raises(ValueError, match="slugifies to empty"):
            _slugify_site_id("🔥💯🎉")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="slugifies to empty"):
            _slugify_site_id("   ")

    def test_repeated_separators_collapse(self) -> None:
        assert _slugify_site_id("foo!!!bar...baz") == "foo_bar_baz"

    def test_strips_leading_trailing_underscores(self) -> None:
        assert _slugify_site_id("!!hello!!") == "hello"

    def test_kanji_stripped(self) -> None:
        assert _slugify_site_id("Tokyo 東京 site") == "tokyo_site"


def test_the_order_site_carries_the_identity_the_configurator_submitted() -> None:
    """The box's first wizard page shows these so the customer can confirm it is the
    ISO built for their site: customer, site name and order id come from the order."""
    # Arrange
    from src.orders.configurator_payload import ConfiguratorPayload
    from src.orders.configurator_payload_test import JS_PAYLOAD
    from src.orchestrator.orchestrator_service import _order_site

    payload = ConfiguratorPayload.model_validate(JS_PAYLOAD)

    # Act
    site = _order_site(payload, order_id="6f1c2a9e-0000-4000-8000-000000000042")

    # Assert
    assert site.customer == payload.operator_org
    assert site.site_name == payload.deployment_site_name
    assert site.order_id == "6f1c2a9e-0000-4000-8000-000000000042"


def test_the_site_callback_points_the_box_at_its_own_order_and_dns_name() -> None:
    """The stack's UserData gets this order's callback URL, its HMAC token and the hostname the
    platform will write for it; nothing is stored per order."""
    # Arrange
    from src.dns.site_identity import site_hostname, token_matches
    from src.orchestrator.orchestrator_service import _site_callback

    order_id = "6f1c2a9e-0000-4000-8000-000000000042"

    # Act
    callback = _site_callback(
        secret="s3cret",
        platform_url="https://platform.arcnode.io",
        order_id=order_id,
        site_id="nevada_facility_2",
    )

    # Assert
    assert (
        callback.url
        == f"https://platform.arcnode.io/platform-api/sites/{order_id}/address"
    )
    assert callback.hostname == site_hostname("nevada_facility_2", order_id)
    assert token_matches("s3cret", order_id, callback.token)


def test_archiving_keeps_the_summary_edp_api_filled_in() -> None:
    """The counts arrive on the completed job's refs; the rebuilt ref must still carry them."""
    # Arrange
    import asyncio

    from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef, ArtifactSummary
    from src.orchestrator.orchestrator_service import OrchestratorService

    class FakeS3:
        async def archive_from_url(self, _source: str, *, key: str) -> tuple[str, int]:
            return f"https://platform/{key}", 1234

    service = OrchestratorService.__new__(OrchestratorService)
    service._s3 = FakeS3()
    service._to_absolute_url = lambda url: url
    ref = ArtifactRef(
        kind=ArtifactKind.BOM,
        format="json",
        url="https://edp/bom.json",
        summary=ArtifactSummary(line_items=19, vendors=11),
    )

    # Act
    new_ref, size = asyncio.run(service._archive_ref("order-1", ref))

    # Assert
    assert new_ref.summary == ArtifactSummary(line_items=19, vendors=11)
    assert size == 1234


@pytest.mark.asyncio
async def test_the_bundle_zips_every_manifest_file_for_the_order() -> None:
    """The order's manifest files go into its arcnode.zip, under its order id."""
    # Arrange
    from src.bundle.bundle_record import BundleFile
    from src.manifest.manifest_record import (
        ManifestArtifact,
        ManifestFile,
        ManifestSection,
    )
    from src.orchestrator.orchestrator_service import OrchestratorService

    class RecordingBundle:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[BundleFile]]] = []

        async def build(self, *, order_id: str, files: list[BundleFile]) -> int:
            self.calls.append((order_id, files))
            return 0

    bundle = RecordingBundle()
    service = OrchestratorService.__new__(OrchestratorService)
    service._bundle = bundle  # type: ignore[attr-defined]
    sections = {
        ManifestSection.ENGINEERING_DRAWINGS: [
            ManifestArtifact(
                code="D1",
                name="DTM",
                subtitle=None,
                files=[
                    ManifestFile(format="JSON", size_bytes=1, url="s3://b/dtm.json")
                ],
            )
        ]
    }

    # Act
    await service._build_bundle("abc123", sections)

    # Assert
    assert bundle.calls == [
        ("abc123", [BundleFile(path="D1/dtm.json", url="s3://b/dtm.json")])
    ]
