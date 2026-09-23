"""SizingService — verbatim proxy to edp-api's closed-form sizing preview.

CONTRACT §4.3: body in = body out. No parsing or validation of the request
or response shape here — edp-api owns SizingPreviewRequest/SizingPreview
(CONTRACT §4.2); duplicating that schema on this side would just be a
second copy to keep in sync, same reasoning as ConfiguratorPayload's
forward-verbatim policy. Raw bytes in, raw httpx.Response out — no JSON
re-parse/re-serialize round-trip that could alter float formatting or key
order.
"""

from typing import Final

import httpx

PROXY_TIMEOUT_SECONDS: Final[float] = 10.0


class SizingService:
    """Stateless proxy client for edp-api's POST /edp-api/sizing/preview."""

    def __init__(
        self, *, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        # Reason: `transport` is test-only DI (httpx.MockTransport) — None in
        # production lets httpx.AsyncClient pick its real network transport.
        self._base_url = base_url
        self._transport = transport

    async def preview(self, body: bytes) -> httpx.Response:
        """POST the raw request body straight through; return the raw response."""
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=PROXY_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            return await client.post(
                "/edp-api/sizing/preview",
                content=body,
                headers={"content-type": "application/json"},
            )
