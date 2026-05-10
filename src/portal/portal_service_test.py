"""Unit tests for `PortalService.render` — pure HTML builder, no I/O.

Locks the prereq vocabulary in place so the portal HTML keeps mirroring the
six-vendor-token CFN parameter contract (Tiger access+secret+project, Aura
client_id+secret+tenant). Drift here = misled operators in delivery emails.
"""

from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef
from src.orders.orders_record import DeliveryPath, OrderEmsDelivery
from src.portal.portal_service import PortalService

APK_URL: str = "https://arcnode-public.s3.example/ems-hmi/latest.apk"
ORDER_ID: str = "abcd1234-5678-90ef-1234-567890abcdef"


def _service() -> PortalService:
    return PortalService(ems_hmi_apk_url=APK_URL)


def _delivery() -> OrderEmsDelivery:
    return OrderEmsDelivery(
        path=DeliveryPath.CFN_STANDARD,
        template_url="https://example.com/orders/x/ems-stack.yaml",
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        kind=ArtifactKind.BOM,
        format="json",
        url="https://example.com/orders/x/bom.json",
    )


def test_render_includes_six_vendor_token_prereqs() -> None:
    """Prereqs section names every token operator must paste at create-stack."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert — the four token-collection rows
    assert "Tiger Cloud — Access Key + Secret Key" in html
    assert "Tiger Cloud — Project ID" in html
    assert "Neo4j Aura — OAuth Client ID + Secret" in html
    assert "Neo4j Aura — Tenant ID" in html


def test_render_does_not_mention_neon() -> None:
    """Neon is gone — Aurora replaces it via native CFN. Stale text would mislead."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert
    assert "Neon" not in html
    assert "neon.tech" not in html


def test_render_states_aurora_is_provisioned_automatically() -> None:
    """Operator must understand Aurora needs no setup on their side."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert
    assert "Aurora Postgres is provisioned automatically" in html


def test_render_includes_vendor_console_locations() -> None:
    """Each prereq row shows where in the vendor console to find the value."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert — sample of the per-row 'where to find it' hints
    assert "Tiger Console &gt; Settings &gt; API Keys" in html
    assert "Aura Console &gt; Account &gt; API Keys" in html
    assert "Aura Console &gt; Account &gt; Tenants" in html


def test_render_links_to_vendor_setup_guides_not_signup_pages() -> None:
    """Per PM contract: links go to docs, not signup pages."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert
    assert "docs.tigerdata.com" in html
    assert "neo4j.com/docs/aura" in html
    assert "[setup guide]" in html


def test_render_prereqs_appear_before_cfn_download_link() -> None:
    """Operator reads prereqs first, then downloads the template."""
    # Arrange + Act
    html = _service().render(
        order_id=ORDER_ID, artifacts=[_artifact()], delivery=_delivery()
    )

    # Assert
    prereqs_pos = html.find("Prerequisites")
    download_pos = html.find("Download CFN template")
    assert 0 <= prereqs_pos < download_pos
