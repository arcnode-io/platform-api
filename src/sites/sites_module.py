"""Sites module — DI assembly for the cloud box address callback."""

import uuid

from src.dns.dns_client import DnsClient
from src.orchestrator.orchestrator_service import _slugify_site_id
from src.orders.order_entity import Order
from src.sites.site_address_service import SiteAddressService
from src.sites.sites_controller import SitesController


async def site_id_of_order(order_id: str) -> str | None:
    """The order's site slug (the one baked into its template), or None if there's no such order."""
    try:
        key = uuid.UUID(order_id)
    except ValueError:
        return None
    order = await Order.get_or_none(id=key)
    if order is None:
        return None
    return _slugify_site_id(order.payload["deployment_site_name"])


class SitesModule:
    """Single point of DI for the address callback."""

    def __init__(
        self,
        *,
        dns_api_user: str,
        dns_client_ip: str,
        namecheap_api_key: str,
        token_secret: str,
    ) -> None:
        self.service = SiteAddressService(
            dns=DnsClient(
                api_user=dns_api_user,
                api_key=namecheap_api_key,
                client_ip=dns_client_ip,
            ),
            token_secret=token_secret,
            site_id_of=site_id_of_order,
        )
        self.router = SitesController(service=self.service).router
