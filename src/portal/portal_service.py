"""PortalService — renders the operator-facing index.html.

Pure string builder; no I/O. Caller uploads the result to S3 and emails the URL.
"""

import html
from typing import Final

from src.edp_client.edp_artifacts import EdpArtifact
from src.orders.orders_record import OrderEmsDelivery

# Three managed-service signups the operator must complete before launching
# the CFN stack — paste each connection string into the matching CFN param.
PREREQ_SIGNUPS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "Neon",
        "https://neon.tech",
        "Postgres for relational config + pgvector store (one URL, both DBs)",
    ),
    (
        "Neo4j Aura",
        "https://neo4j.com/cloud/aura/",
        "Managed graph database for the chatbot",
    ),
    (
        "Timescale Cloud",
        "https://www.timescale.com/cloud",
        "Time-series telemetry store",
    ),
)


class PortalService:
    """Builds the HTML artifact index for one delivered order."""

    def __init__(self, *, ems_hmi_apk_url: str) -> None:
        self._apk_url = ems_hmi_apk_url

    def render(
        self,
        *,
        order_id: str,
        artifacts: list[EdpArtifact],
        delivery: OrderEmsDelivery,
    ) -> str:
        """Return the HTML body: artifacts + prereqs + download CTA + APK."""
        artifact_html = "\n".join(self._render_artifact(a) for a in artifacts)
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
            f"<ul>\n{artifact_html}\n</ul>\n"
            f"{prereqs_html}\n"
            "<h2>EMS Deployment</h2>\n"
            f"{launch_html}\n"
            "<h2>EMS Mobile App (Android)</h2>\n"
            f'<p><a href="{apk}">{apk}</a></p>\n'
            "</body>\n"
            "</html>\n"
        )

    @staticmethod
    def _render_artifact(artifact: EdpArtifact) -> str:
        """One <li> per artifact with a link per format slot."""
        rows: list[str] = []
        for u in artifact.urls:
            fmt = html.escape(u.format)
            if u.url:
                href = html.escape(u.url, quote=True)
                rows.append(f'    <a href="{href}">{fmt}</a>')
            elif u.pending:
                rows.append(f"    {fmt} (pending {html.escape(u.pending)})")
        body = "<br>\n".join(rows)
        return f"<li><strong>{html.escape(artifact.name)}</strong><br>\n{body}</li>"

    @staticmethod
    def _render_prereqs() -> str:
        """Three managed-service signups required *before* launching the CFN stack."""
        items = "\n".join(
            f"  <li><strong>{html.escape(name)}</strong> — "
            f'<a href="{html.escape(url, quote=True)}">sign up</a> — '
            f"{html.escape(desc)}.</li>"
            for name, url, desc in PREREQ_SIGNUPS
        )
        return (
            "<h2>Prerequisites — sign up before launching</h2>\n"
            "<p>The CFN stack requires three managed-service connection strings as "
            "<strong>required parameters with no defaults</strong>. CloudFormation "
            "will refuse to deploy if any are missing.</p>\n"
            f"<ol>\n{items}\n</ol>\n"
            "<p>Paste each connection string into the matching CFN parameter "
            "(<code>NeonConnectionString</code>, <code>Neo4jConnectionString</code>, "
            "<code>TimescaleConnectionString</code>) when running "
            "<code>aws cloudformation create-stack</code> or via Console.</p>"
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
