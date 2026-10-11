"""Unit tests for `DnsClient` — Namecheap's setHosts replaces every record on
the domain, so an upsert must send the records already there plus the new one.

Uses `httpx.MockTransport` (httpx's own public API) injected via the constructor.
"""

from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from src.dns.dns_client import DnsClient, DnsRecord, RecordType

API_USER = "iotresister"
API_KEY = "test-key"  # nosec B105 — fake, unit test only
CLIENT_IP = "1.2.3.4"
NS = "http://api.namecheap.com/xml.response"

GET_HOSTS_OK = f"""<?xml version="1.0" encoding="utf-8"?>
<ApiResponse Status="OK" xmlns="{NS}">
  <Errors />
  <CommandResponse Type="namecheap.domains.dns.getHosts">
    <DomainDNSGetHostsResult Domain="arcnode.io" IsUsingOurDNS="true">
      <host HostId="1" Name="@" Type="CNAME" Address="d1.cloudfront.net." MXPref="10" TTL="1800" />
      <host HostId="2" Name="ems" Type="A" Address="173.211.12.43" MXPref="10" TTL="60" />
    </DomainDNSGetHostsResult>
  </CommandResponse>
</ApiResponse>"""

SET_HOSTS_OK = f"""<?xml version="1.0" encoding="utf-8"?>
<ApiResponse Status="OK" xmlns="{NS}">
  <Errors />
  <CommandResponse Type="namecheap.domains.dns.setHosts">
    <DomainDNSSetHostsResult Domain="arcnode.io" IsSuccess="true" />
  </CommandResponse>
</ApiResponse>"""

SET_HOSTS_ERROR = f"""<?xml version="1.0" encoding="utf-8"?>
<ApiResponse Status="ERROR" xmlns="{NS}">
  <Errors><Error Number="1011150">Invalid request IP: 1.2.3.4</Error></Errors>
</ApiResponse>"""


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> DnsClient:
    return DnsClient(
        api_user=API_USER,
        api_key=API_KEY,
        client_ip=CLIENT_IP,
        transport=httpx.MockTransport(handler),
    )


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.read().decode()).items()}


@pytest.mark.asyncio
async def test_upsert_sends_the_existing_records_plus_the_new_one() -> None:
    # Arrange
    sent: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = _form(request)
        sent.append(form)
        if form["Command"] == "namecheap.domains.dns.getHosts":
            return httpx.Response(200, text=GET_HOSTS_OK)
        return httpx.Response(200, text=SET_HOSTS_OK)

    client = _client(handler)

    # Act
    await client.upsert_record(
        "arcnode.io",
        DnsRecord(host="platform", type=RecordType.A, address="5.6.7.8", ttl=60),
    )

    # Assert — the second call is setHosts with all three records
    set_hosts = sent[1]
    assert set_hosts["Command"] == "namecheap.domains.dns.setHosts"
    assert (set_hosts["SLD"], set_hosts["TLD"]) == ("arcnode", "io")
    assert (set_hosts["HostName1"], set_hosts["RecordType1"]) == ("@", "CNAME")
    assert set_hosts["Address1"] == "d1.cloudfront.net."
    assert (set_hosts["HostName2"], set_hosts["Address2"]) == ("ems", "173.211.12.43")
    assert (set_hosts["HostName3"], set_hosts["RecordType3"]) == ("platform", "A")
    assert (set_hosts["Address3"], set_hosts["TTL3"]) == ("5.6.7.8", "60")
    assert set_hosts["MXPref3"] == "10"
    assert "HostName4" not in set_hosts


@pytest.mark.asyncio
async def test_upsert_replaces_a_record_with_the_same_host_and_type() -> None:
    # Arrange
    sent: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = _form(request)
        sent.append(form)
        if form["Command"] == "namecheap.domains.dns.getHosts":
            return httpx.Response(200, text=GET_HOSTS_OK)
        return httpx.Response(200, text=SET_HOSTS_OK)

    client = _client(handler)

    # Act
    await client.upsert_record(
        "arcnode.io",
        DnsRecord(host="ems", type=RecordType.A, address="9.9.9.9", ttl=60),
    )

    # Assert — still two records; ems now points at the new address
    set_hosts = sent[1]
    assert (set_hosts["HostName2"], set_hosts["Address2"]) == ("ems", "9.9.9.9")
    assert "HostName3" not in set_hosts


@pytest.mark.asyncio
async def test_credentials_travel_in_the_body_not_the_url() -> None:
    # Arrange
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = request.url.query.decode()
        seen["key"] = _form(request)["ApiKey"]
        seen["ip"] = _form(request)["ClientIp"]
        return httpx.Response(200, text=GET_HOSTS_OK)

    client = _client(handler)

    # Act
    records = await client.list_records("arcnode.io")

    # Assert
    assert seen["query"] == ""
    assert (seen["key"], seen["ip"]) == (API_KEY, CLIENT_IP)
    assert records == [
        DnsRecord(
            host="@", type=RecordType.CNAME, address="d1.cloudfront.net.", ttl=1800
        ),
        DnsRecord(host="ems", type=RecordType.A, address="173.211.12.43", ttl=60),
    ]


@pytest.mark.asyncio
async def test_an_api_error_raises_with_namecheaps_message() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SET_HOSTS_ERROR)

    client = _client(handler)

    # Act + Assert
    with pytest.raises(RuntimeError, match="Invalid request IP"):
        await client.list_records("arcnode.io")
