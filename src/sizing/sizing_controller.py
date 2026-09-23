"""Sizing HTTP controller — POST /platform-api/sizing/preview.

Verbatim proxy to edp-api's closed-form sizing preview (CONTRACT §4.3).
Same CORS as /orders — that's the app-wide CORSMiddleware in app_module.py,
nothing route-specific needed here.
"""

from classy_fastapi import Routable, post
from fastapi import Request, Response

from src.sizing.sizing_service import SizingService


class SizingController(Routable):
    """Single-route controller — a dumb proxy, no business logic of its own."""

    def __init__(self, service: SizingService) -> None:
        super().__init__()
        self._service = service

    @post(
        "/platform-api/sizing/preview",
        tags=["Sizing"],
        summary="Verbatim proxy to edp-api's closed-form sizing preview",
    )
    async def preview(self, request: Request) -> Response:
        """Body in = body out. Relays edp-api's status code + JSON body
        unchanged — 422 included, edp-api owns the schema, not us."""
        body = await request.body()
        upstream = await self._service.preview(body)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type="application/json",
        )
