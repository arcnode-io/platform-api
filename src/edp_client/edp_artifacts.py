"""DTOs mirroring edp-api response shapes.

Source of truth: edp-api/readme.md `Core Types` section. Hand-mirrored for now;
codegen from edp-api's OpenAPI export is the planned next step.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class JobStatus(StrEnum):
    """Mirrors edp-api JobStatus."""

    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ArtifactKind(StrEnum):
    """Mirrors edp-api ArtifactKind."""

    BOM = "bom"
    COMPUTE_CONTAINER_3D = "compute_container_3d"
    GRID_CONTAINER_3D = "grid_container_3d"
    INTERFACE_PLATE = "interface_plate"
    SLD = "sld"
    PID_COOLING = "pid_cooling"
    COMMS_DIAGRAM = "comms_diagram"
    CABLE_HOSE_SCHEDULE = "cable_hose_schedule"
    INSTALLATION_GRAPH = "installation_graph"
    DTM = "dtm"


class ArtifactRef(BaseModel):
    """One artifact entry — flat, one per (kind, format[, plate_id])."""

    kind: ArtifactKind
    format: str  # json | xlsx | dxf | pdf | step | glb
    url: str
    plate_id: str | None = None  # only when kind=INTERFACE_PLATE


class JobCreated(BaseModel):
    """edp-api POST /edp-api/jobs 202 body. URLs known up front (deterministic keys)."""

    job_id: UUID
    status_url: str
    edp_artifact_urls: list[ArtifactRef]


class JobResult(BaseModel):
    """edp-api GET /edp-api/jobs/{id} body."""

    status: JobStatus
    edp_artifact_urls: list[ArtifactRef]
    error: str | None = None  # set when status=failed
