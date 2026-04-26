"""DTOs mirroring edp-api response shapes.

Shape matches `edp-api/src/jobs/job_record.py` + `edp-api/src/generators/artifact_models.py`.
Kept narrow to what platform-api actually consumes from the response.
"""

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel


class EdpJobStatus(StrEnum):
    """Mirrors edp-api JobStatus."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class EdpDeliveryPath(StrEnum):
    """Mirrors edp-api DeliveryPath."""

    CFN_STANDARD = "cfn_standard"
    CFN_GOVCLOUD = "cfn_govcloud"
    ISO = "iso"


class EdpEmsDelivery(BaseModel):
    """edp-api emits routing decision only; URLs filled by platform-api."""

    path: EdpDeliveryPath
    ems_mode: str


class EdpArtifactUrl(BaseModel):
    """One format/URL slot per artifact."""

    format: str
    url: Optional[str] = None
    pending: Optional[str] = None


class EdpArtifact(BaseModel):
    """One EDP artifact entry — has 1+ format/URL pairs."""

    name: str
    urls: list[EdpArtifactUrl]


class EdpPostJobResponse(BaseModel):
    """edp-api POST /edp-api/jobs immediate 202 body."""

    job_id: str
    status_url: str
    submitted_at: str


class EdpGetJobResponse(BaseModel):
    """edp-api GET /edp-api/jobs/{id} response on completion."""

    job_id: str
    status: EdpJobStatus
    deployment_uuid: str
    edp_artifacts: list[EdpArtifact]
    ems_delivery: Optional[EdpEmsDelivery] = None
    completed_at: Optional[str] = None
    flags: list[dict[str, object]] = []
