"""PortalService — renders the operator-facing index.html.

Pure string builder; no I/O. Caller uploads the result to S3 and emails the URL.
"""

import html
from collections import defaultdict
from typing import Final

from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef
from src.orders.orders_record import OrderEmsDelivery

# Three managed-service connection strings the operator must collect before
# launching the CFN stack — links go to vendor docs (setup guides), not to
# signup pages, so customers find their own onboarding path.
PREREQ_DOCS: Final[tuple[tuple[str, str], ...]] = (
    ("Neon connection string", "https://neon.tech/docs"),
    ("Neo4j Aura connection string", "https://neo4j.com/docs/aura/"),
    ("TimescaleDB connection string", "https://docs.timescale.com/"),
)

# Display labels for ArtifactKind. Order = display order in portal.
KIND_LABELS: Final[tuple[tuple[ArtifactKind, str], ...]] = (
    (ArtifactKind.BOM,                  "Bill of Materials"),
    (ArtifactKind.COMPUTE_CONTAINER_3D, "Compute Container 3D"),
    (ArtifactKind.GRID_CONTAINER_3D,    "Grid Container 3D"),
    (ArtifactKind.INTERFACE_PLATE,      "Interface Plates"),
    (ArtifactKind.SLD,                  "Single Line Diagram"),
    (ArtifactKind.PID_COOLING,          "P&ID — Cooling System"),
    (ArtifactKind.COMMS_DIAGRAM,        "Communication Network Diagram"),
    (ArtifactKind.CABLE_HOSE_SCHEDULE,  "Cable and Hose Schedule"),
    (ArtifactKind.INSTALLATION_GRAPH,   "Installation Graph"),
    (ArtifactKind.DTM,                  "Device Topology Manifest"),
)


class PortalService:
    """Builds the HTML artifact index for one delivered order."""

    def __init__(self, *, ems_hmi_apk_url: str) -> None:
        self._apk_url = ems_hmi_apk_url

    def render(
        self,
        *,
        order_id: str,
        artifacts: list[ArtifactRef],
        delivery: OrderEmsDelivery,
    ) -> str:
        """Return the HTML body: artifacts + prereqs + download CTA + APK."""
        artifact_html = self._render_artifacts(artifacts)
        prereqs_html = self._render_prereqs()
        launch_html = self._render_launch(delivery)
        apk = html.escape(self._apk_url, quote=True)
        return (
            "<!doctype html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            f"<title>ARCNODE deployment package — {html.escape(order_id)}</title>\n"
            "</head>\n"
            "<body>\n"
            "<h1>ARCNODE deployment package</h1>\n"
            f"<p>Order: <code>{html.escape(order_id)}</code></p>\n"
            "<h2>EDP Artifacts</h2>\n"
            f"{artifact_html}\n"
            f"{prereqs_html}\n"
            "<h2>EMS Deployment</h2>\n"
            f"{launch_html}\n"
            "<h2>EMS Mobile App (Android)</h2>\n"
            f'<p><a href="{apk}">{apk}</a></p>\n'
            "</body>\n"
            "</html>\n"
        )

    @staticmethod
    def _render_artifacts(artifacts: list[ArtifactRef]) -> str:
        """Group flat ArtifactRef list by kind, render in canonical order."""
        by_kind: dict[ArtifactKind, list[ArtifactRef]] = defaultdict(list)
        for a in artifacts:
            by_kind[a.kind].append(a)
        sections: list[str] = []
        for kind, label in KIND_LABELS:
            refs = by_kind.get(kind, [])
            if not refs:
                continue
            sections.append(PortalService._render_kind_section(label, kind, refs))
        return "\n".join(sections)

    @staticmethod
    def _render_kind_section(
        label: str, kind: ArtifactKind, refs: list[ArtifactRef]
    ) -> str:
        """Render one kind block. Plates get sub-grouped by plate_id."""
        if kind == ArtifactKind.INTERFACE_PLATE:
            by_plate: dict[str, list[ArtifactRef]] = defaultdict(list)
            for r in refs:
                by_plate[r.plate_id or "(unknown)"].append(r)
            plate_blocks = "\n".join(
                f"  <li><strong>{html.escape(pid)}</strong><br>\n"
                f"    {PortalService._render_format_links(plate_refs)}\n"
                "  </li>"
                for pid, plate_refs in by_plate.items()
            )
            return (
                f"<h3>{html.escape(label)}</h3>\n<ul>\n{plate_blocks}\n</ul>"
            )
        return (
            f"<h3>{html.escape(label)}</h3>\n"
            f"<p>{PortalService._render_format_links(refs)}</p>"
        )

    @staticmethod
    def _render_format_links(refs: list[ArtifactRef]) -> str:
        """One `<a>` per format, joined with ` · `."""
        return " · ".join(
            f'<a href="{html.escape(r.url, quote=True)}">{html.escape(r.format)}</a>'
            for r in refs
        )

    @staticmethod
    def _render_prereqs() -> str:
        """Checklist of three connection strings the operator collects up front.

        Per PM contract: links go to vendor *docs* (setup guides), not signup
        pages — operators find their own onboarding path.
        """
        items = "\n".join(
            f"  <li>&#9744; {html.escape(name)} "
            f'&nbsp;&nbsp;<a href="{html.escape(url, quote=True)}">[setup guide]</a></li>'
            for name, url in PREREQ_DOCS
        )
        return (
            "<h2>Prerequisites</h2>\n"
            "<p>Before deploying this stack:</p>\n"
            f"<ul>\n{items}\n</ul>\n"
            "<p>The stack will hard fail on deploy without these.</p>"
        )

    @staticmethod
    def _render_launch(delivery: OrderEmsDelivery) -> str:
        """Download CTA for the per-order CFN yaml. ISO path: placeholder."""
        path = html.escape(delivery.path.value)
        mode = html.escape(delivery.ems_mode)
        if not delivery.template_url:
            return f"<p>Path: {path} — link not yet available.</p>"
        download = html.escape(delivery.template_url, quote=True)
        return (
            f"<p>Path: {path}, mode: {mode}</p>\n"
            f'<p><a href="{download}" download>Download CFN template '
            "(ems-stack.yaml)</a> — run from any partition with "
            "<code>aws cloudformation create-stack</code> or upload via "
            "your AWS Console.</p>"
        )
