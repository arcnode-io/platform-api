"""DeploymentManifest — the structured shape that drives portal HTML + manifest.json.

Built by `ManifestService` from an order + archived ArtifactRefs + delivery info.
Two consumers:

1. `PortalService` — Jinja2-renders the per-order delivery page from this shape.
2. The `manifest.json` artifact dropped alongside the page; ops/CI can grep for
   bundle ids, file sizes, signed flags without parsing HTML.

Several fields are placeholder until later phases land — they're prefixed
`mock_` in `ManifestService.build` so a single grep finds them at swap time.
"""

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel


class ManifestSection(StrEnum):
    """Which of the three columns an artifact lands in on the portal page."""

    SYSTEM_IMAGES = "system_images"
    ENGINEERING_DRAWINGS = "engineering_drawings"
    MANIFESTS_AND_SCHEDULES = "manifests_and_schedules"


class ManifestFile(BaseModel):
    """One downloadable file under an artifact (one row's chip in the portal)."""

    format: str  # "DXF", "ISO", "JSON", "APK", ...
    size_bytes: int
    url: str


class ManifestArtifact(BaseModel):
    """One artifact row in the portal.

    `code` is a position-based label (A1, A2 in System Images; D1..D5 in
    Engineering Drawings; M1..M3 in Manifests & Schedules). Not stable across
    deliveries — recomputed per render from artifact ordering.

    `subtitle` is a one-line description (e.g., "Debian 12 · linux-rt 6.6"
    or "1,284 items · 47 vendors"). Currently sourced from the
    `MOCK_ARTIFACT_METADATA` table; will move to edp-api emission later.
    """

    code: str  # "A1", "D2", "M3"
    name: str
    subtitle: str
    files: list[ManifestFile]


class DeploymentManifest(BaseModel):
    """Top-level manifest for one delivery.

    Serializable to JSON for the manifest.json artifact and also passed to
    PortalService.render as the template context.
    """

    site_slug: str  # "brookside-dc-1" — URL-safe, lowercase, dash-separated
    site_display_name: str  # "Brookside DC-1" — operator-facing
    bundle_id: str  # "ARCNODE-EMS-1.0.0"
    revision: int
    supersedes: Optional[str] = None  # prior bundle_id, or None on first delivery
    built_at: datetime
    signed: bool
    key_id: Optional[str] = None  # truncated public-key fingerprint when signed=True
    total_size_bytes: int
    total_file_count: int
    artifact_count: int
    bundle_url: Optional[str] = None  # arcnode.zip — None until bundle phase ships
    bundle_curl_url: Optional[str] = None  # the curl one-liner shown in the header
    # Cloud delivery (CFN path): SYSTEM_IMAGES renders as "Edge & Connectivity"
    # (C codes) + the portal shows the gateway install terminal strip.
    cloud: bool = False
    sections: dict[ManifestSection, list[ManifestArtifact]]
