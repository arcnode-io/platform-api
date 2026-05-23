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
    """Render-time metadata for one ArtifactKind."""

    def __init__(self, *, section: ManifestSection, name: str, subtitle: str) -> None:
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
        subtitle="MOCK 1,284 items · 47 vendors",
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
        subtitle="MOCK 4 plates · BESS, cooling, and comms",
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
        subtitle="MOCK 318 runs · cu · fiber · glycol · CDA",
    ),
    ArtifactKind.INSTALLATION_GRAPH: ArtifactMetadata(
        section=ManifestSection.ENGINEERING_DRAWINGS,
        name="Installation Graph",
        subtitle="Install order · torque specs",
    ),
    ArtifactKind.DTM: ArtifactMetadata(
        section=ManifestSection.MANIFESTS_AND_SCHEDULES,
        name="Device Topology Manifest",
        # MOCK SUBTITLE — replace with computed "{n} devices · addressing + bus map".
        subtitle="MOCK 142 devices · addressing + bus map",
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
        subtitle="MOCK Android · arm64-v8a · minSdk 30",
    ),
    # MOCK SUBTITLE — replace with a real CFN template version once we version
    # the rendered yaml.
    "aws_deployment": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="AWS Deployment",
        subtitle="MOCK CloudFormation template (per-order)",
    ),
    # ISO path's system image — air-gapped appliance .iso baked per-customer.
    "on_prem_appliance": ArtifactMetadata(
        section=ManifestSection.SYSTEM_IMAGES,
        name="On-Prem Appliance",
        subtitle="Debian Bookworm · hybrid ISO · 8c/32GB/256GB SSD min",
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
