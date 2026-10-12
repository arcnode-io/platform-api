"""Bundle HTTP controller — GET /<site-slug>-<order6>/arcnode.zip.

Redirects to a short-lived presigned S3 URL, so the zip never streams through the API.
"""

from classy_fastapi import Routable, get
from fastapi import HTTPException, status
from fastapi.responses import RedirectResponse

from src.aws.s3_service import S3Service
from src.bundle.bundle_path import parse_bundle_path, prefix_bounds
from src.orders.order_entity import Order, OrderStatus

# Reason: curl follows the redirect straight away, so a short-lived link is enough.
REDIRECT_EXPIRY_S: int = 300


class BundleController(Routable):
    """The public download link printed in each order's portal header."""

    def __init__(self, s3: S3Service) -> None:
        super().__init__()
        self._s3 = s3

    @get(
        "/{bundle_path}/arcnode.zip",
        tags=["Bundle"],
        summary="Redirect to the order's arcnode.zip",
        response_class=RedirectResponse,
    )
    async def download(self, bundle_path: str) -> RedirectResponse:
        """302 to a presigned S3 URL for a completed order's zip. 404 otherwise."""
        try:
            _, prefix = parse_bundle_path(bundle_path)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        low, high = prefix_bounds(prefix)
        matches = await Order.filter(id__gte=low, id__lte=high).limit(2)
        if len(matches) != 1 or matches[0].status != OrderStatus.COMPLETE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bundle not found")
        key = f"orders/{matches[0].id}/arcnode.zip"
        url = await self._s3.generate_presigned_url(
            key, expiration_seconds=REDIRECT_EXPIRY_S
        )
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
