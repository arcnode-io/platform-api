"""ManifestService — composes a `DeploymentManifest` from one order's data.

Inputs (all known by the orchestrator at portal-render time):
- `site_display_name` — from ConfiguratorPayload.deployment_site_name
- `built_at` — current UTC timestamp
- `archived` — list of (ArtifactRef, size_bytes) tuples post-S3-archive
- `system_artifacts` — list of orchestrator-built ManifestArtifact (APK,
  per-order CFN yaml, future ISO image)
- `bundle_url` / `bundle_curl_url` — None for now (bundle phase pending)

Letter codes (A1, D1..D5, M1..M3) are assigned positionally per section using
the `MOCK_ARTIFACT_METADATA` table for kind→section mapping.

Several `mock_*` defaults — revision=1, signed=True with a placeholder key —
are stamped here. Grep `mock_` to find every fake-data swap point.
"""

from datetime import UTC, datetime
from typing import Final

from src.edp_client.edp_artifacts import ArtifactRef
from src.manifest.artifact_metadata import (
    MOCK_ARTIFACT_METADATA,
    SECTION_LETTER,
)
from src.manifest.manifest_record import (
    DeploymentManifest,
    ManifestArtifact,
    ManifestFile,
    ManifestSection,
)

# MOCK — first delivery is rev 1; revision counter belongs on Order entity (Tier 5).
MOCK_REVISION: Final[int] = 1
# MOCK — signing infra not implemented; show the badge for design-fidelity.
MOCK_SIGNED: Final[bool] = True
MOCK_KEY_ID: Final[str] = "0xA3F1...9C72"
# MOCK — bundle phase pending; this URL is what Phase 2 will produce.
MOCK_BUNDLE_CURL_TEMPLATE: Final[str] = "https://delivery.arcnode.io/{slug}/arcnode.zip"
# Bundle ID format. Once versioning lands the trailing semver comes from the
# Order's revision history; today every delivery is "1.0.0".
MOCK_BUNDLE_VERSION: Final[str] = "1.0.0"


class ManifestService:
    """Assemble a DeploymentManifest from raw archived inputs."""

    def build(
        self,
        *,
        site_display_name: str,
        archived: list[tuple[ArtifactRef, int]],
        system_artifacts: list[ManifestArtifact],
        built_at: datetime | None = None,
    ) -> DeploymentManifest:
        """Compose the manifest. `built_at` defaults to now-UTC.

        `system_artifacts` is supplied by the orchestrator — the EMS HMI APK
        (from cfg.yml), the per-order CFN yaml, and (future) the ISO image.
        Each is a fully-formed ManifestArtifact (the orchestrator picks the
        name/subtitle from `MOCK_SYSTEM_IMAGE_TEMPLATES`).
        """
        when = built_at or datetime.now(UTC)
        slug = self._slugify(site_display_name)

        sections: dict[ManifestSection, list[ManifestArtifact]] = {
            ManifestSection.SYSTEM_IMAGES: [],
            ManifestSection.ENGINEERING_DRAWINGS: [],
            ManifestSection.MANIFESTS_AND_SCHEDULES: [],
        }

        # System Images — orchestrator-supplied. APK, CFN yaml, future ISO.
        # Each one is already shaped as a ManifestArtifact (with files inside).
        for art in system_artifacts:
            sections[ManifestSection.SYSTEM_IMAGES].append(art)

        # Engineering drawings + manifests/schedules — fold archived artifacts
        # into per-section ManifestArtifact rows. Multiple files with the same
        # ArtifactKind collapse into one row with multiple chips (per mockup).
        by_kind: dict[str, tuple[ArtifactRef, list[tuple[ArtifactRef, int]]]] = {}
        for ref, size in archived:
            key = ref.kind.value
            if key not in by_kind:
                by_kind[key] = (ref, [])
            by_kind[key][1].append((ref, size))

        for ref_with_files in by_kind.values():
            first_ref, refs_with_sizes = ref_with_files
            meta = MOCK_ARTIFACT_METADATA.get(first_ref.kind)
            if meta is None:
                continue  # unknown kind — skip rather than crash; surface later
            files = [
                ManifestFile(format=r.format.upper(), size_bytes=size, url=r.url)
                for r, size in refs_with_sizes
            ]
            sections[meta.section].append(
                ManifestArtifact(
                    code="",
                    name=meta.name,
                    subtitle=meta.subtitle,
                    files=files,
                )
            )

        self._assign_codes(sections)

        total_size = sum(
            f.size_bytes for arts in sections.values() for a in arts for f in a.files
        )
        total_files = sum(len(a.files) for arts in sections.values() for a in arts)
        artifact_count = sum(len(arts) for arts in sections.values())

        return DeploymentManifest(
            site_slug=slug,
            site_display_name=site_display_name,
            bundle_id=f"ARCNODE-EMS-{MOCK_BUNDLE_VERSION}",
            revision=MOCK_REVISION,
            supersedes=None,
            built_at=when,
            signed=MOCK_SIGNED,
            key_id=MOCK_KEY_ID if MOCK_SIGNED else None,
            total_size_bytes=total_size,
            total_file_count=total_files,
            artifact_count=artifact_count,
            bundle_url=None,  # Bundle phase (Tier 2.4) emits this
            bundle_curl_url=MOCK_BUNDLE_CURL_TEMPLATE.format(slug=slug),
            sections=sections,
        )

    @staticmethod
    def _slugify(name: str) -> str:
        """Turn 'Brookside DC-1' into 'brookside-dc-1'.

        Lowercase, ascii-only, dash-separated. Used for the URL path the curl
        one-liner shows. Not bulletproof (we trust ConfiguratorPayload validation
        upstream) — just enough for typical operator names.
        """
        return "-".join(
            "".join(c if c.isalnum() else " " for c in name.lower()).split()
        )

    @staticmethod
    def _assign_codes(
        sections: dict[ManifestSection, list[ManifestArtifact]],
    ) -> None:
        """Walk each section and stamp A1/A2..., D1/D2..., M1/M2... codes in order."""
        for section, arts in sections.items():
            letter = SECTION_LETTER[section]
            for i, art in enumerate(arts, start=1):
                art.code = f"{letter}{i}"
