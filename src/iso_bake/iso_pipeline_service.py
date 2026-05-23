"""IsoPipelineService — triggers the platform-ems-iso gitlab pipeline + tracks status.

Three operations:
  trigger(order_id, overlay_url) → POST /api/v4/projects/{path}/trigger/pipeline
                                   returns the gitlab pipeline id
  status(pipeline_id)            → GET  /api/v4/projects/{path}/pipelines/{id}
                                   returns PipelineStatus enum
  iso_key(order_id)              → deterministic S3 key the build uploads to

Pure HTTP client. The orchestrator owns when to call these.
"""

from enum import StrEnum
from urllib.parse import quote

import httpx


class PipelineStatus(StrEnum):
    """Coalesced view of gitlab's many in-flight statuses."""

    RUNNING = "running"  # created/pending/preparing/running/scheduled — all "not done"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


_GITLAB_TERMINAL: dict[str, PipelineStatus] = {
    "success": PipelineStatus.SUCCESS,
    "failed": PipelineStatus.FAILED,
    "canceled": PipelineStatus.CANCELED,
    # gitlab also emits 'skipped' for child-pipeline scenarios; treat as canceled
    "skipped": PipelineStatus.CANCELED,
}


class IsoPipelineService:
    """Bridges platform-api's orchestrator to platform-ems-iso's gitlab CI."""

    def __init__(
        self,
        *,
        gitlab_url: str,
        project_path: str,
        trigger_token: str,
        iso_bucket_prefix: str,
        httpx_client: httpx.AsyncClient,
    ) -> None:
        # Reason: project_path is "arcnode-io/platform-ems-iso"; gitlab requires
        # url-encoding the slash so the path-style endpoint resolves.
        self._gitlab_url = gitlab_url.rstrip("/")
        self._project_path_encoded = quote(project_path, safe="")
        self._trigger_token = trigger_token
        self._iso_bucket_prefix = iso_bucket_prefix
        self._client = httpx_client

    async def trigger(self, *, order_id: str, overlay_url: str) -> int:
        """Kick the bake pipeline. Returns gitlab's pipeline id for polling."""
        url = (
            f"{self._gitlab_url}/api/v4/projects/"
            f"{self._project_path_encoded}/trigger/pipeline"
        )
        # gitlab's trigger endpoint takes form-encoded data, not JSON
        data = {
            "token": self._trigger_token,
            "ref": "main",
            "variables[ORDER_ID]": order_id,
            "variables[OVERLAY_URL]": overlay_url,
        }
        resp = await self._client.post(url, data=data)
        if resp.status_code != 201:
            raise RuntimeError(
                f"gitlab trigger failed: {resp.status_code} {resp.text}"
            )
        return int(resp.json()["id"])

    async def status(self, *, pipeline_id: int) -> PipelineStatus:
        """Poll one pipeline; map gitlab's status string into our enum."""
        url = (
            f"{self._gitlab_url}/api/v4/projects/"
            f"{self._project_path_encoded}/pipelines/{pipeline_id}"
        )
        resp = await self._client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"gitlab pipeline status failed: {resp.status_code} {resp.text}"
            )
        raw = resp.json().get("status", "")
        return _GITLAB_TERMINAL.get(raw, PipelineStatus.RUNNING)

    def iso_key(self, *, order_id: str) -> str:
        """S3 key the bake pipeline uploads the finished ISO to. Deterministic."""
        return f"{self._iso_bucket_prefix}/{order_id}/arcnode-ems-{order_id}.iso"
