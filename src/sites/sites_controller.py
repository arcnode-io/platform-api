"""Sites HTTP controller — a cloud box reports its address: POST /platform-api/sites/{order_id}/address."""

from classy_fastapi import Routable, post
from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from src.sites.site_address_service import (
    InvalidSiteAddressError,
    InvalidSiteTokenError,
    SiteRegistrar,
    UnknownOrderError,
)


class AddressRequest(BaseModel):
    """The box's own public address (its Elastic IP)."""

    address: str


class AddressResponse(BaseModel):
    """The DNS name now pointing at the box."""

    hostname: str


class SitesController(Routable):
    """The callback the customer stack's UserData makes."""

    def __init__(self, service: SiteRegistrar) -> None:
        super().__init__()
        self._service = service

    @post(
        "/platform-api/sites/{order_id}/address",
        response_model=AddressResponse,
        tags=["Sites"],
        summary="A cloud box reports its address; its site's DNS name is pointed at it",
    )
    async def register_address(
        self,
        order_id: str,
        body: AddressRequest,
        x_site_token: str = Header(),
    ) -> AddressResponse:
        """Token-gated; 403 wrong token, 404 unknown order, 422 not a public IPv4."""
        try:
            hostname = await self._service.register(
                order_id=order_id, token=x_site_token, address=body.address
            )
        except InvalidSiteTokenError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except UnknownOrderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidSiteAddressError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return AddressResponse(hostname=hostname)
