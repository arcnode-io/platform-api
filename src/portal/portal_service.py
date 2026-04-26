"""PortalService — renders the operator-facing index.html.

Pure string builder; no I/O. Caller uploads the result to S3 and emails the URL.
"""

import html

from src.edp_client.edp_artifacts import EdpArtifact
from src.orders.orders_record import OrderEmsDelivery


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
        """Return the HTML body listing artifacts + EMS launch link + APK link."""
        artifact_html = "\n".join(self._render_artifact(a) for a in artifacts)
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
    def _render_launch(delivery: OrderEmsDelivery) -> str:
        """CFN deep link or ISO placeholder, depending on delivery path."""
        path = html.escape(delivery.path.value)
        mode = html.escape(delivery.ems_mode)
        if delivery.launch_url:
            href = html.escape(delivery.launch_url, quote=True)
            return f'<p><a href="{href}">Launch EMS stack</a> ' f"({mode}, {path})</p>"
        return f"<p>Path: {path} — link not yet available.</p>"
