"""SiteAddressService — a cloud box reports its address, its site's DNS name follows.

The customer's stack runs in their own AWS account, so it can't write our DNS zone. Its
UserData calls platform-api with the order's token and the box's Elastic IP, and platform-api
(which holds the Namecheap key) writes `<site>-<order>.arcnode.io` → that address."""

import ipaddress
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

from src.dns.dns_client import DnsRecord, RecordType
from src.dns.site_identity import DOMAIN, site_host_label, site_hostname, token_matches

# Short on purpose: the record is set once, and a customer fixing a typo shouldn't wait on caches.
RECORD_TTL: Final[int] = 60


class DnsWriter(Protocol):
    """The one DNS call the service makes."""

    async def upsert_record(self, domain: str, record: DnsRecord) -> None:
        """Set one record on the domain, keeping the others."""
        ...


class SiteRegistrar(Protocol):
    """What the HTTP layer needs from the service."""

    async def register(self, *, order_id: str, token: str, address: str) -> str:
        """Point the order's site name at `address`; return the hostname."""
        ...


class InvalidSiteTokenError(Exception):
    """The token isn't this order's."""


class UnknownOrderError(Exception):
    """No order with this id."""


class InvalidSiteAddressError(Exception):
    """The address isn't a public IPv4 address."""


class SiteAddressService:
    """Validates a box's callback and writes its site's A record."""

    def __init__(
        self,
        *,
        dns: DnsWriter,
        token_secret: str,
        site_id_of: Callable[[str], Awaitable[str | None]],
    ) -> None:
        self._dns = dns
        self._token_secret = token_secret
        self._site_id_of = site_id_of

    async def register(self, *, order_id: str, token: str, address: str) -> str:
        """Point the order's site name at `address`; return the hostname."""
        if not token_matches(self._token_secret, order_id, token):
            raise InvalidSiteTokenError("token does not match this order")
        site_id = await self._site_id_of(order_id)
        if site_id is None:
            raise UnknownOrderError(f"order {order_id} not found")
        _require_public_ipv4(address)
        await self._dns.upsert_record(
            DOMAIN,
            DnsRecord(
                host=site_host_label(site_id, order_id),
                type=RecordType.A,
                address=address,
                ttl=RECORD_TTL,
            ),
        )
        return site_hostname(site_id, order_id)


def _require_public_ipv4(address: str) -> None:
    """Reject anything that would send a customer's traffic somewhere private or not v4."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise InvalidSiteAddressError(f"{address!r} is not an IP address") from exc
    if parsed.version != 4 or not parsed.is_global:
        raise InvalidSiteAddressError(f"{address} is not a public IPv4 address")
