"""OrchestratorService — composes EdpClient + S3 + SES + CFN + Portal.

Per NestJS clean-orchestrator conventions:
- public method = business intent (`execute`)
- private steps named for their responsibility (`_run_pipeline`, `_archive`,
  `_publish_portal`, `_notify`)
- state transitions extracted into `_mark_*` helpers
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from src.aws.s3_service import S3Service
from src.bundle.bundle_record import BUNDLE_LINK_EXPIRY_S
from src.bundle.bundle_service import BundleService, bundle_files_for, unique_path
from src.aws.ses_service import SesService
from src.cfn.site_callback import SiteCallback
from src.dns.site_identity import site_hostname, site_token
from src.email.resend_service import ResendService
from src.cfn.cfn_service import CfnService
from src.edp_client.edp_artifacts import (
    ArtifactKind,
    ArtifactRef,
    JobResult,
)
from src.edp_client.edp_client_service import EdpClientService
from src.iso.iso_service import IsoService
from src.manifest.artifact_metadata import MOCK_SYSTEM_IMAGE_TEMPLATES
from src.manifest.manifest_record import (
    ManifestArtifact,
    ManifestFile,
    ManifestSection,
)
from src.manifest.manifest_service import ManifestService
from src.orders.configurator_payload import ConfiguratorPayload
from src.orders.order_entity import Order, OrderStatus
from src.orders.orders_record import (
    DeliveryPath,
    OrderEmsDelivery,
    derive_delivery_path,
)
from src.portal.portal_service import PortalService
from src.wizard.order_record import OrderSite


@dataclass(frozen=True)
class _PipelineResult:
    """Output of `_run_pipeline` — what `_mark_complete` needs to persist."""

    edp: JobResult
    archived: list[ArtifactRef]
    delivery: OrderEmsDelivery
    deployment_uuid: str


class OrchestratorService:
    """Drives a single order from PENDING → COMPLETE."""

    def __init__(
        self,
        *,
        edp_client: EdpClientService,
        s3: S3Service,
        ses: SesService | ResendService,
        cfn: CfnService,
        iso: IsoService,
        portal: PortalService,
        manifest: ManifestService,
        bundle: BundleService,
        ems_hmi_apk_url: str,
        ems_industrial_gateway_tarball_url: str,
        site_token_secret: str | None = None,
        platform_public_url: str = "",
    ) -> None:
        self._edp = edp_client
        self._s3 = s3
        self._ses = ses
        self._cfn = cfn
        self._iso = iso
        self._portal = portal
        self._manifest = manifest
        self._bundle = bundle
        self._ems_hmi_apk_url = ems_hmi_apk_url
        self._ems_industrial_gateway_tarball_url = ems_industrial_gateway_tarball_url
        # None (local dev, tests): templates carry no DNS callback and keep the self-signed IP cert.
        self._site_token_secret = site_token_secret
        self._platform_public_url = platform_public_url

    # Public — business intent

    async def execute(self, order: Order) -> None:
        """Drive `order` from PENDING → COMPLETE (or FAILED on any exception)."""
        logging.info("🚀 orchestrator start order=%s", order.id)
        await self._mark_running(order)
        try:
            result = await self._run_pipeline(order)
        except Exception:
            logging.exception("❌ orchestrator failed for order %s", order.id)
            await self._mark_failed(order)
            return
        logging.info("✅ orchestrator complete order=%s", order.id)
        await self._mark_complete(order, result)

    # Pipeline

    async def _run_pipeline(self, order: Order) -> _PipelineResult:
        """Setup → submit → archive → publish portal → notify."""
        logging.info("🔧 aws setup order=%s", order.id)
        await self._setup_aws()
        payload = ConfiguratorPayload.model_validate(order.payload)
        logging.info("⏩ edp submit order=%s", order.id)
        edp = await self._edp.submit_and_wait(payload, deployment_id=order.id)
        logging.info(
            "📥 archive %d artifacts order=%s",
            len(edp.edp_artifact_urls),
            order.id,
        )
        archived = await self._archive(str(order.id), edp)
        logging.info("📦 build delivery order=%s", order.id)
        delivery = await self._build_delivery(str(order.id), payload, archived)
        logging.info("🎨 publish portal order=%s", order.id)
        portal_url = await self._publish_portal(
            str(order.id), payload, archived, delivery
        )
        logging.info("📧 notify %s order=%s", payload.contact_email, order.id)
        await self._notify(payload.contact_email, portal_url)
        return _PipelineResult(
            edp=edp,
            archived=[ref for ref, _ in archived],
            delivery=delivery,
            deployment_uuid=str(order.id),
        )

    async def _setup_aws(self) -> None:
        """Ensure S3 bucket exists + SES sender is verified. Idempotent."""
        await self._s3.ensure_bucket()
        await self._ses.verify_sender()

    async def _archive(
        self, order_id: str, edp: JobResult
    ) -> list[tuple[ArtifactRef, int]]:
        """Re-archive every edp-api artifact into platform-api S3.

        Returns (ref, size_bytes) so the manifest builder can render file-size
        chips without a follow-up HEAD round-trip.
        """
        keys = archive_keys(order_id, [a.url for a in edp.edp_artifact_urls])
        return [
            await self._archive_ref(key, a)
            for key, a in zip(keys, edp.edp_artifact_urls, strict=True)
        ]

    async def _archive_ref(self, key: str, ref: ArtifactRef) -> tuple[ArtifactRef, int]:
        """Stream one artifact's bytes into platform-api S3 at `key`, return (ref, size)."""
        source = self._to_absolute_url(ref.url)
        new_url, size = await self._s3.archive_from_url(source, key=key)
        new_ref = ArtifactRef(
            kind=ref.kind,
            format=ref.format,
            url=new_url,
            plate_id=ref.plate_id,
            summary=ref.summary,
        )
        return new_ref, size

    async def _build_delivery(
        self,
        order_id: str,
        payload: ConfiguratorPayload,
        archived: list[tuple[ArtifactRef, int]],
    ) -> OrderEmsDelivery:
        """Render + upload per-order delivery artifacts; expose their S3 URLs.

        ISO path: the base ISO with the order's site + DTM baked into /order.
        CFN paths: yaml + presigned DTM URL — operator runs from their partition.
        Both get the site from `_order_site`, so they can't disagree.
        """
        path = derive_delivery_path(payload.aws_partition)
        site = _order_site(payload, order_id=order_id)
        self._find_dtm_url(archived)  # validate it exists
        if path == DeliveryPath.ISO:
            baked = await self._iso.bake(order_id=order_id, site=site)
            return OrderEmsDelivery(
                path=path, iso_url=baked.url, iso_size_bytes=baked.size_bytes
            )
        dtm_key = f"orders/{order_id}/dtm.json"
        dtm_presigned_url = await self._s3.generate_presigned_url(dtm_key)
        template = self._cfn.render_template(
            deployment_uuid=order_id,
            dtm_url=dtm_presigned_url,
            site_id=site.site_id,
            market_region=site.market_region,
            settlement_point=site.settlement_point,
            deployment_context=payload.deployment_context,
            site_callback=(
                _site_callback(
                    secret=self._site_token_secret,
                    platform_url=self._platform_public_url,
                    order_id=order_id,
                    site_id=site.site_id,
                )
                if self._site_token_secret
                else None
            ),
        )
        template_url = await self._s3.upload_yaml(
            f"orders/{order_id}/ems-stack.yaml", template
        )
        return OrderEmsDelivery(path=path, template_url=template_url)

    async def _publish_portal(
        self,
        order_id: str,
        payload: ConfiguratorPayload,
        archived: list[tuple[ArtifactRef, int]],
        delivery: OrderEmsDelivery,
    ) -> str:
        """Build manifest, render portal HTML + manifest.json, upload both.

        Returns the portal index.html public URL (which is what the email
        body links to).
        """
        system_artifacts = await self._build_system_artifacts(delivery)
        bundle_url = await self._s3.generate_presigned_url(
            f"orders/{order_id}/arcnode.zip", expiration_seconds=BUNDLE_LINK_EXPIRY_S
        )
        manifest = self._manifest.build(
            bundle_url=bundle_url,
            site_display_name=payload.deployment_site_name,
            archived=archived,
            system_artifacts=system_artifacts,
            # Cloud (CFN) deliveries render the Edge & Connectivity column +
            # the gateway install strip; ISO deliveries keep System Images.
            cloud=delivery.template_url is not None,
        )
        html = self._portal.render(manifest=manifest)
        manifest_json = self._portal.render_manifest_json(manifest=manifest)
        await self._build_bundle(order_id, manifest.sections)
        await self._s3.upload_json(f"orders/{order_id}/manifest.json", manifest_json)
        return await self._s3.upload_html(f"orders/{order_id}/index.html", html)

    async def _build_bundle(
        self,
        order_id: str,
        sections: dict[ManifestSection, list[ManifestArtifact]],
    ) -> None:
        """Zip every manifest file into the order's arcnode.zip (the curl link's target)."""
        await self._bundle.build(order_id=order_id, files=bundle_files_for(sections))

    async def _build_system_artifacts(
        self, delivery: OrderEmsDelivery
    ) -> list[ManifestArtifact]:
        """Compose the System Images section: APK from cfg.yml + per-order
        CFN yaml (cloud) or per-order appliance ISO (on-prem)."""
        artifacts: list[ManifestArtifact] = []

        if delivery.iso_url:
            iso_meta = MOCK_SYSTEM_IMAGE_TEMPLATES["appliance_iso"]
            artifacts.append(
                ManifestArtifact(
                    code="",
                    name=iso_meta.name,
                    subtitle=iso_meta.subtitle,
                    files=[
                        ManifestFile(
                            format="ISO",
                            size_bytes=delivery.iso_size_bytes or 0,
                            url=delivery.iso_url,
                        )
                    ],
                )
            )

        apk_meta = MOCK_SYSTEM_IMAGE_TEMPLATES["ems_field_client"]
        apk_size = await self._s3.head_size(self._ems_hmi_apk_url)
        artifacts.append(
            ManifestArtifact(
                code="",
                name=apk_meta.name,
                subtitle=apk_meta.subtitle,
                files=[
                    ManifestFile(
                        format="APK",
                        size_bytes=apk_size,
                        url=self._ems_hmi_apk_url,
                    )
                ],
            )
        )

        # Cloud paths get the per-order CFN yaml as a System Images artifact.
        if delivery.template_url:
            cfn_meta = MOCK_SYSTEM_IMAGE_TEMPLATES["aws_deployment"]
            cfn_size = await self._s3.head_size(delivery.template_url)
            artifacts.append(
                ManifestArtifact(
                    code="",
                    name=cfn_meta.name,
                    subtitle=cfn_meta.subtitle,
                    files=[
                        ManifestFile(
                            format="YAML",
                            size_bytes=cfn_size,
                            url=delivery.template_url,
                        )
                    ],
                )
            )

            # Cloud customers also need the on-prem gateway image to run next to
            # their devices (dials the cloud broker). Per-release tarball, same
            # for every cloud order. Appliance/ISO orders bake it in instead.
            # sha256 sidecar published by gateway CI next to the tarball; chip
            # renders only when it exists (head_size 0 = absent = omit).
            gw_meta = MOCK_SYSTEM_IMAGE_TEMPLATES["industrial_gateway"]
            gw_url = self._ems_industrial_gateway_tarball_url
            gw_size = await self._s3.head_size(gw_url)
            gw_files = [ManifestFile(format="TGZ", size_bytes=gw_size, url=gw_url)]
            sha_url = f"{gw_url}.sha256"
            sha_size = await self._s3.head_size(sha_url)
            if sha_size > 0:
                gw_files.append(
                    ManifestFile(format="SHA256", size_bytes=sha_size, url=sha_url)
                )
            artifacts.append(
                ManifestArtifact(
                    code="",
                    name=gw_meta.name,
                    subtitle=gw_meta.subtitle,
                    files=gw_files,
                )
            )

        return artifacts

    async def _notify(self, to: str, portal_url: str) -> None:
        """Email the operator the portal link + a brief prereq pointer.

        Body deliberately short — full prereq detail (token names, where to
        find them, doc links) lives in the portal page so this email stays
        plain-text-friendly and survives email-client mangling.
        """
        await self._ses.send_delivery_email(
            to=to,
            subject="ARCNODE deployment package ready",
            body_text=(
                f"Your ARCNODE deployment package is ready.\n\nPortal: {portal_url}\n"
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
        order.deployment_uuid = result.deployment_uuid
        order.edp_artifacts = [a.model_dump(mode="json") for a in result.archived]
        order.ems_delivery = result.delivery.model_dump(mode="json")
        await order.save()
        logging.info(
            "order %s -> complete (deployment=%s)",
            order.id,
            result.deployment_uuid,
        )

    # Helpers

    def _to_absolute_url(self, url: str) -> str:
        """edp-api emits absolute s3:// or https:// URLs; pass through.

        Kept as a hook for the case where edp-api emits relative paths in tests.
        """
        if url.startswith(("http://", "https://", "s3://")):
            return url
        return f"{self._edp._base_url.rstrip('/')}{url}"

    @staticmethod
    def _find_dtm_url(archived: list[tuple[ArtifactRef, int]]) -> str:
        """Locate the DTM's archived URL — required for the CFN launch link."""
        for ref, _ in archived:
            if ref.kind == ArtifactKind.DTM:
                return ref.url
        raise ValueError("DTM url missing in archived artifacts")


_SITE_ID_RX = re.compile(r"[^a-z0-9]+")


def _order_site(payload: ConfiguratorPayload, *, order_id: str) -> OrderSite:
    """The order's site as every EMS delivery bakes it in — CFN template or
    ISO. market_region is None when the grid path has no settlement point
    (off-grid, or a market_region not yet pinned to one)."""
    return OrderSite(
        site_id=_slugify_site_id(payload.deployment_site_name),
        market_region=(
            payload.grid.market_region.value
            if payload.grid.market_region is not None
            else None
        ),
        settlement_point=payload.grid.settlement_point,
        customer=payload.operator_org,
        site_name=payload.deployment_site_name,
        order_id=order_id,
    )


def _site_callback(
    *, secret: str, platform_url: str, order_id: str, site_id: str
) -> SiteCallback:
    """What this order's stack calls to get its DNS name: URL, HMAC token, hostname."""
    return SiteCallback(
        url=f"{platform_url}/platform-api/sites/{order_id}/address",
        token=site_token(secret, order_id),
        hostname=site_hostname(site_id, order_id),
    )


def _slugify_site_id(name: str) -> str:
    """Operator's site name -> ascii snake_case slug for MQTT topics + DB.

    Strips ALL non-ascii-alnum runs to underscores: emojis, accents, kanji,
    cyrillic — all gone. Lowercase. Empty result raises (e.g. all-emoji input)
    so a bad submission fails the order instead of writing 'sites//devices/...'.

    Examples:
      'Nevada Facility 2' -> 'nevada_facility_2'
      'Brookside DC-1'    -> 'brookside_dc_1'
      'Café 🔥 Site'      -> 'caf_site'
      '🔥💯'              -> ValueError
    """
    slug = _SITE_ID_RX.sub("_", name.lower()).strip("_")
    if not slug:
        raise ValueError(f"deployment_site_name slugifies to empty: {name!r}")
    return slug


def archive_keys(order_id: str, urls: list[str]) -> list[str]:
    """One S3 key per edp-api file, named by its file name.

    Reason: two files with the same name (two plates' assembly.step) would overwrite
    each other in the order's folder, so later ones get a numbered name.
    """
    taken: set[str] = set()
    keys: list[str] = []
    for url in urls:
        name = unique_path(url.rsplit("/", 1)[-1], taken)
        taken.add(name)
        keys.append(f"orders/{order_id}/{name}")
    return keys
