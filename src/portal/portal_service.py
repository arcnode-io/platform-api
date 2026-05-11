"""PortalService — renders the per-customer delivery portal.

Jinja2-templated. Output is a static HTML string that the orchestrator
uploads to S3 alongside the `manifest.json` artifact.

Single template (`templates/portal.html`) with the SOVEREIGN dark theme
inlined as `<style>`. SOLARPUNK light theme is a future commit.

The DeploymentManifest is the entire input contract; everything operator-facing
flows from its fields. See `src/manifest/manifest_record.py` for the shape.
"""

import json
from pathlib import Path
from typing import Final, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.manifest.artifact_metadata import SECTION_LABEL
from src.manifest.manifest_record import DeploymentManifest, ManifestSection
from src.orders.orders_record import DeliveryPath, OrderEmsDelivery

TEMPLATE_DIR: Final[Path] = Path(__file__).parent / "templates"
TEMPLATE_NAME: Final[str] = "portal.html"


def _filesize(n: int) -> str:
    """Format bytes as '38.4 MB' / '566 B' / '2.46 GB' (mockup-matching scale).

    Decimal (1000) base — matches modern OS file managers (macOS Finder,
    Windows Explorer post-Win11) and the mockup's hand-picked values. We
    deliberately don't use binary (1024) prefixes; operator-facing copy
    follows operator-facing conventions, not bit-twiddling tradition.
    """
    if n < 1000:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB")
    val = float(n)
    idx = -1
    while val >= 1000 and idx < len(units) - 1:
        val /= 1000
        idx += 1
    # 2 decimals at GB+ for design fidelity (mockup: "2.46 GB"); 1 below.
    return f"{val:.2f} {units[idx]}" if idx >= 2 else f"{val:.1f} {units[idx]}"


def _split_curl_url(url: str) -> tuple[str, str]:
    """Split URL into (prefix-with-trailing-slash, filename) for chip-coloring."""
    if "/" not in url:
        return "", url
    prefix, _, filename = url.rpartition("/")
    return f"{prefix}/", filename


_SECTION_NUMBERS: Final[dict[ManifestSection, str]] = {
    ManifestSection.SYSTEM_IMAGES: "01",
    ManifestSection.ENGINEERING_DRAWINGS: "02",
    ManifestSection.MANIFESTS_AND_SCHEDULES: "03",
}

_SECTION_RENDER_ORDER: Final[tuple[ManifestSection, ...]] = (
    ManifestSection.SYSTEM_IMAGES,
    ManifestSection.ENGINEERING_DRAWINGS,
    ManifestSection.MANIFESTS_AND_SCHEDULES,
)


# Vendor prereqs the operator must collect *before* `aws cloudformation
# create-stack`. These six tokens land as Parameters in the per-order CFN
# template; the in-template Lambdas use them to provision Tiger Cloud +
# Neo4j Aura over their REST APIs at stack-create time. Aurora Postgres
# is provisioned natively by CFN — no operator action needed.
#
# Per PM contract (2026-05-10): doc links point at vendor *documentation*
# pages (where to find the token), not signup pages.
CFN_PREREQS: Final[list[dict[str, str]]] = [
    {
        "vendor": "Tiger Cloud",
        "token": "Access Key",
        "where": "Console > Settings > API Keys",
        "doc_url": "https://docs.tigerdata.com/use-timescale/latest/services/api-keys/",
    },
    {
        "vendor": "Tiger Cloud",
        "token": "Secret Key",
        "where": "Shown once at access-key creation — copy immediately",
        "doc_url": "https://docs.tigerdata.com/use-timescale/latest/services/api-keys/",
    },
    {
        "vendor": "Tiger Cloud",
        "token": "Project ID",
        "where": "Projects page (UUID under each project name)",
        "doc_url": "https://docs.tigerdata.com/use-timescale/latest/projects/",
    },
    {
        "vendor": "Neo4j Aura",
        "token": "Client ID",
        "where": "Aura Console > API Keys > Create",
        "doc_url": "https://neo4j.com/docs/aura/classic/platform/api/authentication/",
    },
    {
        "vendor": "Neo4j Aura",
        "token": "Client Secret",
        "where": "Shown once at API-key creation — copy immediately",
        "doc_url": "https://neo4j.com/docs/aura/classic/platform/api/authentication/",
    },
    {
        "vendor": "Neo4j Aura",
        "token": "Tenant ID",
        "where": "Aura Console > Account > Tenant settings",
        "doc_url": "https://neo4j.com/docs/aura/classic/platform/api/specification/",
    },
]

# Aurora Postgres is provisioned natively by CFN — informational only,
# rendered as a callout under the Prerequisites checklist.
AURORA_NOTE: Final[str] = (
    "Aurora Postgres is provisioned automatically by the CFN stack — "
    "no operator tokens required."
)


def _is_cfn_path(delivery: Optional[OrderEmsDelivery]) -> bool:
    """True when the delivery routes via CloudFormation (standard or GovCloud)."""
    if delivery is None:
        return False
    return delivery.path in (DeliveryPath.CFN_STANDARD, DeliveryPath.CFN_GOVCLOUD)


class PortalService:
    """Renders the delivery portal HTML + matching manifest.json."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["filesize"] = _filesize

    def render(
        self,
        *,
        manifest: DeploymentManifest,
        delivery: Optional[OrderEmsDelivery] = None,
    ) -> str:
        """Render the portal HTML page (uploaded to S3 as `index.html`).

        `delivery` drives the Prerequisites + Download CFN template section
        (CFN paths only). ISO and missing-delivery cases skip those blocks.
        """
        section_specs = [
            {
                "key": s,
                "num": _SECTION_NUMBERS[s],
                "label": SECTION_LABEL[s],
            }
            for s in _SECTION_RENDER_ORDER
        ]
        curl_prefix, curl_filename = _split_curl_url(manifest.bundle_curl_url or "")
        template = self._env.get_template(TEMPLATE_NAME)
        show_cfn = _is_cfn_path(delivery) and bool(
            delivery and delivery.template_url
        )
        return template.render(
            manifest=manifest,
            section_specs=section_specs,
            curl_prefix=curl_prefix,
            curl_filename=curl_filename,
            show_cfn_section=show_cfn,
            cfn_template_url=delivery.template_url if delivery else None,
            cfn_prereqs=CFN_PREREQS if show_cfn else [],
            aurora_note=AURORA_NOTE,
        )

    def render_manifest_json(self, *, manifest: DeploymentManifest) -> str:
        """Serialize the manifest as the `manifest.json` artifact (pretty JSON)."""
        return json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
