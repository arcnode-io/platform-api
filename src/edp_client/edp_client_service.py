"""EdpClientService — async httpx wrapper around edp-api.

Submits a sizing job and polls until completion. Returns the parsed
`EdpGetJobResponse` so the orchestrator can stream artifact URLs into S3.
"""

import asyncio
import logging
from typing import Final

import httpx

from src.edp_client.edp_artifacts import (
    EdpGetJobResponse,
    EdpJobStatus,
    EdpPostJobResponse,
)
from src.orders.configurator_payload import ConfiguratorPayload

POLL_INTERVAL_SECONDS: Final[float] = 0.5
POLL_TIMEOUT_SECONDS: Final[float] = 60.0


class EdpJobFailedError(Exception):
    """Raised when edp-api returns status=failed (system-level error in the EDP pipeline)."""


class EdpClientService:
    """Async client for edp-api. Stateless aside from the base URL."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url

    async def submit_and_wait(self, payload: ConfiguratorPayload) -> EdpGetJobResponse:
        """POST a job, poll until terminal state, return the final response."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
            post = await client.post(
                "/edp-api/jobs", json=payload.model_dump(mode="json")
            )
            post.raise_for_status()
            submit = EdpPostJobResponse.model_validate(post.json())
            logging.info("edp-api job submitted: %s", submit.job_id)
            return await self._poll(client, submit.job_id)

    @staticmethod
    async def _poll(client: httpx.AsyncClient, job_id: str) -> EdpGetJobResponse:
        deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"/edp-api/jobs/{job_id}")
            r.raise_for_status()
            body = EdpGetJobResponse.model_validate(r.json())
            if body.status == EdpJobStatus.COMPLETE:
                logging.info("edp-api job complete: %s", job_id)
                return body
            if body.status == EdpJobStatus.FAILED:
                raise EdpJobFailedError(
                    f"edp-api job {job_id} failed: flags={body.flags}"
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise TimeoutError(
            f"edp-api job {job_id} did not reach terminal state in {POLL_TIMEOUT_SECONDS}s"
        )
