"""OrchestratorService — composes EdpClient + S3 + SES + CFN + Portal.

Per NestJS clean-orchestrator conventions:
- public method = business intent (`execute`)
- private steps named for their responsibility (`_run_pipeline`, `_archive`,
  `_publish_portal`, `_notify`)
- state transitions extracted into `_mark_*` helpers
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.aws.s3_service import S3Service
from src.aws.ses_service import SesService
from src.cfn.cfn_service import CfnService
from src.edp_client.edp_artifacts import (
    EdpArtifact,
    EdpArtifactUrl,
    EdpDeliveryPath,
    EdpGetJobResponse,
)
from src.edp_client.edp_client_service import EdpClientService
from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.order_entity import Order, OrderStatus
from src.orders.orders_record import OrderEmsDelivery
from src.portal.portal_service import PortalService

DTM_ARTIFACT_NAME: str = "Device Topology Manifest"


@dataclass(frozen=True)
class _PipelineResult:
    """Output of `_run_pipeline` — what `_mark_complete` needs to persist."""

    edp: EdpGetJobResponse
    archived: list[EdpArtifact]
    delivery: OrderEmsDelivery


class OrchestratorService:
    """Drives a single order from PENDING → COMPLETE."""

    def __init__(
        self,
        *,
        edp_client: EdpClientService,
        s3: S3Service,
        ses: SesService,
        cfn: CfnService,
        portal: PortalService,
    ) -> None:
        self._edp = edp_client
        self._s3 = s3
        self._ses = ses
        self._cfn = cfn
        self._portal = portal

    # Public — business intent

    async def execute(self, order: Order) -> None:
        """Drive `order` from PENDING → COMPLETE (or FAILED on any exception)."""
        await self._mark_running(order)
        try:
            result = await self._run_pipeline(order)
        except Exception:
            logging.exception("orchestrator failed for order %s", order.id)
            await self._mark_failed(order)
            return
        await self._mark_complete(order, result)

    # Pipeline

    async def _run_pipeline(self, order: Order) -> _PipelineResult:
        """Setup → submit → archive → publish portal → notify."""
        await self._setup_aws()
        payload = ConfiguratorPayload.model_validate(order.payload)
        edp = await self._edp.submit_and_wait(payload)
        archived = await self._archive(str(order.id), edp)
        delivery = await self._build_delivery(str(order.id), edp, archived)
        portal_url = await self._publish_portal(str(order.id), archived, delivery)
        await self._notify(payload.contact_email, portal_url)
        return _PipelineResult(edp=edp, archived=archived, delivery=delivery)

    async def _setup_aws(self) -> None:
        """Ensure S3 bucket exists + SES sender is verified. Idempotent."""
        await self._s3.ensure_bucket()
        await self._ses.verify_sender()

    async def _archive(
        self, order_id: str, edp: EdpGetJobResponse
    ) -> list[EdpArtifact]:
        """Re-archive every real (non-stub) edp-api artifact into platform-api S3."""
        return [
            EdpArtifact(
                name=artifact.name,
                urls=[await self._archive_url(order_id, u) for u in artifact.urls],
            )
            for artifact in edp.edp_artifacts
        ]

    async def _archive_url(
        self, order_id: str, url_entry: EdpArtifactUrl
    ) -> EdpArtifactUrl:
        """Stream one URL slot's bytes to S3 — or pass through if it's a stub."""
        if url_entry.url is None:
            return url_entry
        source = self._to_absolute_url(url_entry.url)
        key = f"orders/{order_id}/{source.rsplit('/', 1)[-1]}"
        new_url = await self._s3.archive_from_url(source, key=key)
        return EdpArtifactUrl(format=url_entry.format, url=new_url)

    async def _build_delivery(
        self,
        order_id: str,
        edp: EdpGetJobResponse,
        archived: list[EdpArtifact],
    ) -> OrderEmsDelivery:
        """Render + upload per-order CFN template; expose its S3 URL for download.

        ISO path: skip CFN bits entirely (air-gapped delivery is a future build).
        CFN paths (standard + govcloud): same yaml — operator downloads and runs
        from their own partition.
        """
        assert edp.ems_delivery is not None, "edp-api must emit ems_delivery"
        if edp.ems_delivery.path == EdpDeliveryPath.ISO:
            return OrderEmsDelivery(
                path=edp.ems_delivery.path,
                ems_mode=edp.ems_delivery.ems_mode,
            )
        dtm_url = self._find_dtm_url(archived)
        template = self._cfn.render_template(
            deployment_uuid=edp.deployment_uuid,
            dtm_url=dtm_url,
            ems_mode=edp.ems_delivery.ems_mode,
        )
        template_url = await self._s3.upload_yaml(
            f"orders/{order_id}/ems-stack.yaml", template
        )
        return OrderEmsDelivery(
            path=edp.ems_delivery.path,
            ems_mode=edp.ems_delivery.ems_mode,
            template_url=template_url,
        )

    async def _publish_portal(
        self,
        order_id: str,
        archived: list[EdpArtifact],
        delivery: OrderEmsDelivery,
    ) -> str:
        """Render index.html and upload to S3; return its public URL."""
        body = self._portal.render(
            order_id=order_id, artifacts=archived, delivery=delivery
        )
        return await self._s3.upload_html(f"orders/{order_id}/index.html", body)

    async def _notify(self, to: str, portal_url: str) -> None:
        """Email the operator a one-line link to the portal page."""
        await self._ses.send_delivery_email(
            to=to,
            subject="ARCNODE deployment package ready",
            body_text=(
                "Your ARCNODE deployment package is ready.\n\n"
                f"Portal: {portal_url}\n"
            ),
        )

    # Status transitions

    @staticmethod
    async def _mark_running(order: Order) -> None:
        order.status = OrderStatus.RUNNING
        await order.save()

    @staticmethod
    async def _mark_failed(order: Order) -> None:
        order.status = OrderStatus.FAILED
        order.completed_at = datetime.now(UTC)
        await order.save()

    @staticmethod
    async def _mark_complete(order: Order, result: _PipelineResult) -> None:
        order.status = OrderStatus.COMPLETE
        order.completed_at = datetime.now(UTC)
        order.edp_job_id = result.edp.job_id
        order.deployment_uuid = result.edp.deployment_uuid
        order.edp_artifacts = [a.model_dump() for a in result.archived]
        order.ems_delivery = result.delivery.model_dump()
        order.flags = list(result.edp.flags)
        await order.save()
        logging.info(
            "order %s -> complete (deployment=%s)",
            order.id,
            result.edp.deployment_uuid,
        )

    # Helpers

    def _to_absolute_url(self, url: str) -> str:
        """edp-api emits relative URLs; expand against the configured base URL."""
        if url.startswith(("http://", "https://")):
            return url
        return f"{self._edp._base_url.rstrip('/')}{url}"

    @staticmethod
    def _find_dtm_url(archived: list[EdpArtifact]) -> str:
        """Locate the DTM's archived URL — required for the CFN launch link."""
        for a in archived:
            if a.name == DTM_ARTIFACT_NAME:
                for u in a.urls:
                    if u.url:
                        return u.url
        raise ValueError(f"{DTM_ARTIFACT_NAME} url missing in archived artifacts")
