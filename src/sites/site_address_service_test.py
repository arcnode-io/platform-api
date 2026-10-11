"""A cloud box tells platform-api its address; platform-api points the site's DNS name at it.

Token-gated, address-checked: only the stack built from an order can set that order's record,
and only to a public IPv4 address."""

import pytest

from src.dns.dns_client import DnsRecord, RecordType
from src.dns.site_identity import DOMAIN, site_hostname, site_token
from src.sites.site_address_service import (
    InvalidSiteAddressError,
    InvalidSiteTokenError,
    SiteAddressService,
    UnknownOrderError,
)

ORDER_ID = "6f1c2a9e-0000-4000-8000-000000000042"
SECRET = "s3cret"
EIP = "3.228.116.51"


class FakeDns:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, DnsRecord]] = []

    async def upsert_record(self, domain: str, record: DnsRecord) -> None:
        self.upserts.append((domain, record))


async def _site_id(order_id: str) -> str | None:
    return "nevada_facility_2" if order_id == ORDER_ID else None


def _service(dns: FakeDns) -> SiteAddressService:
    return SiteAddressService(dns=dns, token_secret=SECRET, site_id_of=_site_id)


@pytest.mark.asyncio
async def test_a_valid_callback_points_the_sites_name_at_the_box() -> None:
    # Arrange
    dns = FakeDns()

    # Act
    hostname = await _service(dns).register(
        order_id=ORDER_ID, token=site_token(SECRET, ORDER_ID), address=EIP
    )

    # Assert
    assert hostname == site_hostname("nevada_facility_2", ORDER_ID)
    assert dns.upserts == [
        (
            DOMAIN,
            DnsRecord(
                host="nevada-facility-2-6f1c2a", type=RecordType.A, address=EIP, ttl=60
            ),
        )
    ]


@pytest.mark.asyncio
async def test_a_wrong_token_writes_nothing() -> None:
    # Arrange
    dns = FakeDns()

    # Act + Assert
    with pytest.raises(InvalidSiteTokenError):
        await _service(dns).register(order_id=ORDER_ID, token="nope", address=EIP)
    assert dns.upserts == []


@pytest.mark.asyncio
async def test_an_unknown_order_writes_nothing() -> None:
    # Arrange
    dns = FakeDns()
    other = "a1b2c3d4-0000-4000-8000-000000000099"

    # Act + Assert
    with pytest.raises(UnknownOrderError):
        await _service(dns).register(
            order_id=other, token=site_token(SECRET, other), address=EIP
        )
    assert dns.upserts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "not-an-ip", "2001:db8::1", ""],
)
async def test_only_a_public_ipv4_address_is_accepted(address: str) -> None:
    # Arrange
    dns = FakeDns()

    # Act + Assert
    with pytest.raises(InvalidSiteAddressError):
        await _service(dns).register(
            order_id=ORDER_ID, token=site_token(SECRET, ORDER_ID), address=address
        )
    assert dns.upserts == []
