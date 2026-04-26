"""OrchestratorService — composes EdpClient + S3 + SES into the order flow.

Per Q3 lock: the integration test asserts (1) S3 bytes archived,
(2) SES email captured. This service is the path that produces both.
"""

import logging
from datetime import UTC, datetime

from src.aws.s3_service import S3Service
from src.aws.ses_service import SesService
from src.edp_client.edp_artifacts import EdpArtifact, EdpArtifactUrl, EdpGetJobResponse
from src.edp_client.edp_client_service import EdpClientService
from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.order_entity import Order, OrderStatus


class OrchestratorService:
    """Drives a single order from PENDING → COMPLETE."""

    def __init__(
        self,
        *,
        edp_client: EdpClientService,
        s3: S3Service,
        ses: SesService,
        ems_hmi_apk_url: str,
    ) -> None:
        self._edp = edp_client
        self._s3 = s3
        self._ses = ses
        self._ems_hmi_apk_url = ems_hmi_apk_url

    async def execute(self, order: Order) -> None:
        """Full pipeline. Caller (OrdersService) schedules this in BackgroundTasks."""
        order.status = OrderStatus.RUNNING
        await order.save()

        try:
            await self._s3.ensure_bucket()
            await self._ses.verify_sender()
            payload = ConfiguratorPayload.model_validate(order.payload)
            edp = await self._edp.submit_and_wait(payload)
            archived = await self._archive_artifacts(str(order.id), edp)
            await self._send_delivery_email(payload.contact_email, archived)
        except Exception:
            logging.exception("orchestrator failed for order %s", order.id)
            order.status = OrderStatus.FAILED
            order.completed_at = datetime.now(UTC)
            await order.save()
            return

        order.status = OrderStatus.COMPLETE
        order.completed_at = datetime.now(UTC)
        order.edp_job_id = edp.job_id
        order.deployment_uuid = edp.deployment_uuid
        order.edp_artifacts = [a.model_dump() for a in archived]
        order.ems_delivery = edp.ems_delivery.model_dump() if edp.ems_delivery else None
        order.flags = list(edp.flags)
        await order.save()
        logging.info(
            "order %s -> complete (deployment=%s)", order.id, edp.deployment_uuid
        )

    async def _archive_artifacts(
        self, order_id: str, edp: EdpGetJobResponse
    ) -> list[EdpArtifact]:
        """Re-archive every real (non-stub) edp-api artifact into platform-api S3."""
        archived: list[EdpArtifact] = []
        for artifact in edp.edp_artifacts:
            new_urls: list[EdpArtifactUrl] = []
            for url_entry in artifact.urls:
                if url_entry.url is None:
                    new_urls.append(url_entry)  # stub passes through unchanged
                    continue
                # Reason: edp-api emits relative URLs like /edp-api/artifacts/...; expand
                # to absolute against the configured edp-api base URL.
                source = self._edp_absolute_url(url_entry.url)
                key = self._s3_key(order_id, source)
                new_url = await self._s3.archive_from_url(source, key=key)
                new_urls.append(EdpArtifactUrl(format=url_entry.format, url=new_url))
            archived.append(EdpArtifact(name=artifact.name, urls=new_urls))
        return archived

    def _edp_absolute_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self._edp._base_url.rstrip('/')}{url}"

    @staticmethod
    def _s3_key(order_id: str, source_url: str) -> str:
        filename = source_url.rsplit("/", 1)[-1]
        return f"orders/{order_id}/{filename}"

    async def _send_delivery_email(self, to: str, archived: list[EdpArtifact]) -> None:
        """Plain-text body listing artifacts + the EMS HMI Android app link."""
        lines = ["Your ARCNODE deployment package is ready.", "", "Artifacts:"]
        for artifact in archived:
            lines.append(f"- {artifact.name}")
            for u in artifact.urls:
                if u.url is not None:
                    lines.append(f"    {u.format}: {u.url}")
                elif u.pending:
                    lines.append(f"    {u.format}: (pending {u.pending})")
        lines.extend([
            "",
            "EMS Mobile App (Android):",
            f"  {self._ems_hmi_apk_url}",
        ])
        body = "\n".join(lines)
        await self._ses.send_delivery_email(
            to=to, subject="ARCNODE deployment package ready", body_text=body
        )
