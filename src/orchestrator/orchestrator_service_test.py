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
        async def archive_from_url(
            self,
            _source: str,
            *,
            key: str,
            content_type: str,  # noqa: ARG002
        ) -> tuple[str, int]:
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


def test_archived_artifacts_are_stored_with_their_real_content_type() -> None:
    """A PDF served as application/json won't open in a browser (order 51de5d81's sld.pdf)."""
    # Arrange
    import asyncio

    from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef
    from src.orchestrator.orchestrator_service import OrchestratorService

    class RecordingS3:
        def __init__(self) -> None:
            self.content_types: dict[str, str] = {}

        async def archive_from_url(
            self, _source: str, *, key: str, content_type: str
        ) -> tuple[str, int]:
            self.content_types[key] = content_type
            return f"https://platform/{key}", 1

    s3 = RecordingS3()
    service = OrchestratorService.__new__(OrchestratorService)
    service._s3 = s3
    service._to_absolute_url = lambda url: url
    refs = [
        ArtifactRef(kind=ArtifactKind.SLD, format="pdf", url="https://edp/sld.pdf"),
        ArtifactRef(kind=ArtifactKind.SLD, format="dxf", url="https://edp/sld.dxf"),
        ArtifactRef(
            kind=ArtifactKind.SLD_HMI_SVG, format="svg", url="https://edp/sld_hmi.svg"
        ),
        ArtifactRef(kind=ArtifactKind.BOM, format="xlsx", url="https://edp/bom.xlsx"),
        ArtifactRef(
            kind=ArtifactKind.COMPUTE_CONTAINER_3D,
            format="glb",
            url="https://edp/a.glb",
        ),
    ]

    # Act
    for ref in refs:
        asyncio.run(
            service._archive_ref(f"orders/o/{ref.kind.value}.{ref.format}", ref)
        )

    # Assert
    assert s3.content_types == {
        "orders/o/sld.pdf": "application/pdf",
        "orders/o/sld.dxf": "image/vnd.dxf",
        "orders/o/sld_hmi_svg.svg": "image/svg+xml",
        "orders/o/bom.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "orders/o/compute_container_3d.glb": "model/gltf-binary",
    }


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


def test_colliding_archive_names_get_numbered_keys() -> None:
    """Two edp-api files named assembly.step must not overwrite each other in the order's folder."""
    # Arrange
    from src.orchestrator.orchestrator_service import archive_keys

    urls = [
        "https://edp.example/a/assembly.step",
        "https://edp.example/b/assembly.step",
        "https://edp.example/c/dtm.json",
    ]

    # Act
    keys = archive_keys("abc123", urls)

    # Assert
    assert keys == [
        "orders/abc123/assembly.step",
        "orders/abc123/assembly-2.step",
        "orders/abc123/dtm.json",
    ]


@pytest.mark.asyncio
async def test_a_failed_order_emails_the_contact_with_the_order_id() -> None:
    """A failed build tells the customer, with the order id to quote to support."""
    # Arrange
    from src.orchestrator.orchestrator_service import OrchestratorService

    class RecordingSes:
        def __init__(self) -> None:
            self.sent: list[dict[str, str]] = []

        async def send_delivery_email(
            self, *, to: str, subject: str, body_text: str
        ) -> None:
            self.sent.append({"to": to, "subject": subject, "body_text": body_text})

    ses = RecordingSes()
    service = OrchestratorService.__new__(OrchestratorService)
    service._ses = ses  # type: ignore[attr-defined]

    # Act
    await service._notify_failed(to="ops@acme.io", site_name="bar", order_id="abc123")

    # Assert
    assert len(ses.sent) == 1
    assert ses.sent[0]["to"] == "ops@acme.io"
    assert ses.sent[0]["subject"] == "ARCNODE deployment package failed"
    assert "abc123" in ses.sent[0]["body_text"]
    assert "bar" in ses.sent[0]["body_text"]


@pytest.mark.asyncio
async def test_the_ready_email_names_the_deployment_site() -> None:
    """The ready email carries the site name in subject and body, so a contact with several
    orders can tell them apart in the inbox."""
    # Arrange
    from src.orchestrator.orchestrator_service import OrchestratorService

    class RecordingSes:
        def __init__(self) -> None:
            self.sent: list[dict[str, str]] = []

        async def send_delivery_email(
            self, *, to: str, subject: str, body_text: str
        ) -> None:
            self.sent.append({"to": to, "subject": subject, "body_text": body_text})

    ses = RecordingSes()
    service = OrchestratorService.__new__(OrchestratorService)
    service._ses = ses  # type: ignore[attr-defined]

    # Act
    await service._notify(
        to="ops@acme.io", site_name="manual-qa", portal_url="https://p/portal.html"
    )

    # Assert
    assert ses.sent[0]["subject"] == "ARCNODE deployment package ready: manual-qa"
    assert "manual-qa" in ses.sent[0]["body_text"]
    assert "Portal: https://p/portal.html" in ses.sent[0]["body_text"]
