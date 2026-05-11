"""EdpClientService — async httpx wrapper around edp-api.

POSTs a configurator payload, polls until terminal state, returns the parsed
`JobResult`. The 202 response carries the (deterministic) artifact URLs up
front; we still poll for write-completion before returning to the caller.
"""

import asyncio
import logging
from typing import Final
from uuid import UUID

import httpx

from src.edp_client.edp_artifacts import (
    JobCreated,
    JobResult,
    JobStatus,
)
from src.orders.configurator_payload import ConfiguratorPayload

POLL_INTERVAL_SECONDS: Final[float] = 0.5
# 5 min — covers CI's slower edp-api pipeline (LocalStack S3 fetches +
# Bom/Dtm generation under load). Local dev typically finishes in <10s.
POLL_TIMEOUT_SECONDS: Final[float] = 300.0


class EdpJobFailedError(Exception):
    """Raised when edp-api returns status=failed."""


class EdpClientService:
    """Async client for edp-api. Stateless aside from the base URL."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url

    async def submit_and_wait(
        self, payload: ConfiguratorPayload, deployment_id: UUID
    ) -> JobResult:
        """POST a job, poll until complete/failed, return final result.

        `deployment_id` is platform-api's order id reused as the edp-api
        deployment uuid — single ID generation, deterministic edp-api keys.
        """
        body = payload.model_dump(mode="json") | {"deployment_id": str(deployment_id)}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            post = await client.post("/edp-api/jobs", json=body)
            post.raise_for_status()
            submit = JobCreated.model_validate(post.json())
            logging.info("edp-api job submitted: %s", submit.job_id)
            return await self._poll(client, submit.job_id)

    @staticmethod
    async def _poll(client: httpx.AsyncClient, job_id: UUID) -> JobResult:
        deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"/edp-api/jobs/{job_id}")
            r.raise_for_status()
            body = JobResult.model_validate(r.json())
            if body.status == JobStatus.COMPLETE:
                logging.info("edp-api job complete: %s", job_id)
                return body
            if body.status == JobStatus.FAILED:
                raise EdpJobFailedError(f"edp-api job {job_id} failed: {body.error}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise TimeoutError(
            f"edp-api job {job_id} did not reach terminal state in {POLL_TIMEOUT_SECONDS}s"
        )
