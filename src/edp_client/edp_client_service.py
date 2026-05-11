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
            logging.info("📤 edp POST /jobs deployment=%s", deployment_id)
            post = await client.post("/edp-api/jobs", json=body)
            post.raise_for_status()
            submit = JobCreated.model_validate(post.json())
            logging.info("🎫 edp job submitted: %s", submit.job_id)
            return await self._poll(client, submit.job_id)

    @staticmethod
    async def _poll(client: httpx.AsyncClient, job_id: UUID) -> JobResult:
        loop = asyncio.get_event_loop()
        start = loop.time()
        deadline = start + POLL_TIMEOUT_SECONDS
        # Heartbeat every 30 polls (~15s) so CI logs show the loop is alive
        # while edp-api churns through Bom/Dtm generation.
        heartbeat_every = 30
        ticks = 0
        last_status: JobStatus | None = None
        while loop.time() < deadline:
            r = await client.get(f"/edp-api/jobs/{job_id}")
            r.raise_for_status()
            body = JobResult.model_validate(r.json())
            if body.status != last_status:
                logging.info("🔄 edp job %s status=%s", job_id, body.status.value)
                last_status = body.status
            if body.status == JobStatus.COMPLETE:
                elapsed = loop.time() - start
                logging.info("✅ edp job complete: %s (%.1fs)", job_id, elapsed)
                return body
            if body.status == JobStatus.FAILED:
                logging.error("❌ edp job failed: %s — %s", job_id, body.error)
                raise EdpJobFailedError(f"edp-api job {job_id} failed: {body.error}")
            ticks += 1
            if ticks % heartbeat_every == 0:
                logging.info(
                    "⏳ edp poll job=%s elapsed=%.1fs status=%s",
                    job_id,
                    loop.time() - start,
                    body.status.value,
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        logging.error(
            "⏱️ edp poll timeout job=%s after %.1fs", job_id, POLL_TIMEOUT_SECONDS
        )
        raise TimeoutError(
            f"edp-api job {job_id} did not reach terminal state in {POLL_TIMEOUT_SECONDS}s"
        )
