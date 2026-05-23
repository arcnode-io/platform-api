"""ISO bake module — DI assembly for `IsoBakeService` + `IsoPipelineService`."""

import httpx

from src.iso_bake.iso_bake_service import IsoBakeService
from src.iso_bake.iso_pipeline_service import IsoPipelineService


class IsoBakeModule:
    """Single point of DI for ISO overlay rendering + pipeline triggering."""

    def __init__(
        self,
        *,
        iso_version: str,
        gitlab_url: str,
        project_path: str,
        trigger_token: str,
        iso_bucket_prefix: str,
    ) -> None:
        self.service = IsoBakeService(iso_version=iso_version)
        # Reason: AsyncClient lives for the app's lifetime — fastapi's lifespan
        # would normally own this, but the orchestrator only fires ad-hoc so a
        # module-scoped client is fine. No connection-pool pressure expected.
        self._http = httpx.AsyncClient(timeout=10.0)
        self.pipeline_service = IsoPipelineService(
            gitlab_url=gitlab_url,
            project_path=project_path,
            trigger_token=trigger_token,
            iso_bucket_prefix=iso_bucket_prefix,
            httpx_client=self._http,
        )
