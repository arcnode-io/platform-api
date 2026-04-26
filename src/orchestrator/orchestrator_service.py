"""OrchestratorService — composes EdpClient + S3 + SES into the order flow.

Per NestJS clean-orchestrator conventions:
- public method = business intent (`execute`)
- private steps named for their responsibility (`_run_pipeline`, `_archive`, `_notify`)
- state transitions extracted into `_mark_*` helpers so the public method
  reads as a try/except over the work, not a try/except mixed with bookkeeping
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.aws.s3_service import S3Service
from src.aws.ses_service import SesService
from src.edp_client.edp_artifacts import EdpArtifact, EdpArtifactUrl, EdpGetJobResponse
from src.edp_client.edp_client_service import EdpClientService
from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.order_entity import Order, OrderStatus


@dataclass(frozen=True)
class _PipelineResult:
    """Output of `_run_pipeline` — what `_mark_complete` needs to persist."""

    edp: EdpGetJobResponse
    archived: list[EdpArtifact]


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
        """Setup → submit → archive → notify. One sequential pass."""
        await self._setup_aws()
        payload = ConfiguratorPayload.model_validate(order.payload)
        edp = await self._edp.submit_and_wait(payload)
        archived = await self._archive(str(order.id), edp)
        await self._notify(payload.contact_email, archived)
        return _PipelineResult(edp=edp, archived=archived)

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

    async def _notify(self, to: str, archived: list[EdpArtifact]) -> None:
        """Send the operator the delivery email with archived artifact URLs + APK link."""
        await self._ses.send_delivery_email(
            to=to,
            subject="ARCNODE deployment package ready",
            body_text=self._format_email_body(archived),
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
        order.ems_delivery = (
            result.edp.ems_delivery.model_dump() if result.edp.ems_delivery else None
        )
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

    def _format_email_body(self, archived: list[EdpArtifact]) -> str:
        """Plain-text body listing artifact URLs + the EMS HMI Android app link."""
        lines = ["Your ARCNODE deployment package is ready.", "", "Artifacts:"]
        for artifact in archived:
            lines.append(f"- {artifact.name}")
            for u in artifact.urls:
                if u.url is not None:
                    lines.append(f"    {u.format}: {u.url}")
                elif u.pending:
                    lines.append(f"    {u.format}: (pending {u.pending})")
        lines.extend(["", "EMS Mobile App (Android):", f"  {self._ems_hmi_apk_url}"])
        return "\n".join(lines)
