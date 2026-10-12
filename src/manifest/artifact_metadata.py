"""MOCK_ARTIFACT_METADATA — per-ArtifactKind display data hardcoded for now.

Source-of-truth migration path: edp-api will emit these fields in ArtifactRef
once ADR-005 (DTO codegen + ArtifactRef enrichment) lands. Until then,
platform-api maps `ArtifactKind` → (section, name, subtitle) here.

The `MOCK_` prefix is deliberate — grep `MOCK_` to find every fake-data swap
point in the codebase when wiring up the real source.

Subtitles are mostly from `ems-mockups/portal-dark.webp` per PM design review.
A handful are obviously placeholder ("computed at archive time" should land
once edp-api emits the count). Marked `MOCK SUBTITLE` inline.
"""

from typing import Final

from src.edp_client.edp_artifacts import ArtifactKind
from src.manifest.manifest_record import ManifestSection


class ArtifactMetadata:
    """Render-time metadata for one ArtifactKind. A None subtitle renders nothing."""

    def __init__(
        self, *, section: ManifestSection, name: str, subtitle: str | None
    ) -> None:
        self.section = section
        self.name = name
        self.subtitle = subtitle


MOCK_ARTIFACT_METADATA: Final[dict[ArtifactKind, ArtifactMetadata]] = {
    # System Images section is APK + (future) ISO. APK is injected by orchestrator
    # from cfg.yml; ISO comes from a later ISO-build pipeline. Neither is in
    # ArtifactKind today — when ISO lands we'll add ArtifactKind.ISO_HMI etc.
    ArtifactKind.BOM: ArtifactMetadata(
        section=ManifestSection.MANIFESTS_AND_SCHEDULES,
        name="Bill of Materials",
        # MOCK SUBTITLE — replace with computed "{n} items · {m} vendors" once
        # edp-api emits item/vendor counts in ArtifactRef.
        subtitle="Estimated · 19 line items · 11 vendors",
    ),
    ArtifactKind.COMPUTE_CONTAINER_3D: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Compute Container 3D",
        subtitle="Container shell · racks · DLC manifolds",
    ),
    ArtifactKind.GRID_CONTAINER_3D: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Grid Container 3D",
        subtitle="Switchgear · transformer · PCS",
    ),
    ArtifactKind.INTERFACE_PLATE: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Interface Plates",
        # MOCK SUBTITLE — replace with computed "{n} plates · {kinds}" once
        # edp-api emits plate count + kind summary.
        subtitle=None,  # real value comes from edp-api once it emits the counts
    ),
    ArtifactKind.SLD: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Single Line Diagram",
        subtitle="AC + DC distribution to module level",
    ),
    ArtifactKind.PID_COOLING: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="P&ID — Cooling",
        subtitle="Glycol loop · pumps · valves",
    ),
    ArtifactKind.COMMS_DIAGRAM: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Comms Network",
        subtitle="Modbus · CAN · Ethernet topology",
    ),
    ArtifactKind.CABLE_HOSE_SCHEDULE: ArtifactMetadata(
        section=ManifestSection.MANIFESTS_AND_SCHEDULES,
        name="Cable & Hose Schedule",
        # MOCK SUBTITLE — replace with computed "{n} runs · cu · fiber · glycol · CDA".
        subtitle="Estimated · 81 runs · 4 media kinds",
    ),
    ArtifactKind.INSTALL_SEQUENCE: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Installation Graph",
        subtitle="Install order · torque specs",
    ),
    ArtifactKind.DTM: ArtifactMetadata(
        section=ManifestSection.MANIFESTS_AND_SCHEDULES,
        name="Device Topology Manifest",
        # MOCK SUBTITLE — replace with computed "{n} devices · addressing + bus map".
        subtitle="Estimated · 36 devices · 1 AC bus",
    ),
}


# MOCK_SYSTEM_IMAGE_TEMPLATES — non-edp-api artifacts the orchestrator stitches
# into the System Images section. edp-api emits engineering drawings + manifests;
# system images come from elsewhere (cfg.yml APK URL, per-order CFN render, future
# ISO build). One row per logical system artifact.
MOCK_SYSTEM_IMAGE_TEMPLATES: Final[dict[str, ArtifactMetadata]] = {
    # MOCK SUBTITLE — replace with cfg.yml-emitted Android target metadata once
    # the EMS HMI build pipeline writes a sidecar manifest.
    "ems_field_client": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="EMS Field Client",
        subtitle="Android 7.0+ · APK",
    ),
    # On-prem: the generic installer with this order's site + devices baked
    # in (src/iso/iso_service.py). Presigned, so the link expires.
    "appliance_iso": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="Appliance Installer",
        subtitle=(
            "Debian 13 USB installer · x86-64 · carries your site's devices · "
            "link valid 7 days"
        ),
    ),
    # Copy per delivery-portal-cloud.jsx (C2).
    "aws_deployment": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="CloudFormation Template",
        subtitle="Deploy in your AWS account · stands up the telemetry ingest stack",
    ),
    # Cloud customers run the gateway on-prem (next to their devices) and it
    # dials the cloud broker. Delivered as a docker-save tarball: `docker load`
    # then `docker run` with AWS env creds — the container self-configures
    # from their stack. Copy per delivery-portal-cloud.jsx (C1).
    "industrial_gateway": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="Industrial Gateway",
        subtitle=(
            "OCI container · runs on your local network · "
            "forwards telemetry to the cloud"
        ),
    ),
}


# Letter-code prefix per section. Used by ManifestService to assign A1, D1, M1
# style codes positionally within each section.
SECTION_LETTER: Final[dict[ManifestSection, str]] = {
    ManifestSection.SYSTEM_IMAGES: "A",
    ManifestSection.ENGINEERING_DRAWINGS: "D",
    ManifestSection.MANIFESTS_AND_SCHEDULES: "M",
}


# Display labels for the section headers (e.g., "§ 02 ENGINEERING DRAWINGS").
SECTION_LABEL: Final[dict[ManifestSection, str]] = {
    ManifestSection.SYSTEM_IMAGES: "System Images",
    ManifestSection.ENGINEERING_DRAWINGS: "Engineering Drawings",
    ManifestSection.MANIFESTS_AND_SCHEDULES: "Manifests & Schedules",
}
