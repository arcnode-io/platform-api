"""DnsClient — writes host records on a domain through Namecheap's API.

Namecheap has no "add one record" call: `setHosts` replaces every record on the
domain. So an upsert reads the current records, swaps or appends the one given,
and writes the whole set back. Credentials go in the POST body, never the URL.
"""

import asyncio
import xml.etree.ElementTree as ET  # nosec B405 — parsing Namecheap's own response
from enum import StrEnum
from typing import Final

import httpx
from pydantic import BaseModel

API_URL: Final[str] = "https://api.namecheap.com/xml.response"
NS: Final[dict[str, str]] = {"nc": "http://api.namecheap.com/xml.response"}
GET_HOSTS: Final[str] = "namecheap.domains.dns.getHosts"
SET_HOSTS: Final[str] = "namecheap.domains.dns.setHosts"


class RecordType(StrEnum):
    """The record types we write; Namecheap's own names."""

    A = "A"
    CNAME = "CNAME"
    TXT = "TXT"
    MX = "MX"


class DnsRecord(BaseModel):
    """One host record. `host` is relative to the domain (`@` for the apex)."""

    host: str
    type: RecordType
    address: str
    ttl: int
    mx_pref: int = 10


class DnsClient:
    """Namecheap DNS API client. `client_ip` must be whitelisted on the account."""

    def __init__(
        self,
        *,
        api_user: str,
        api_key: str,
        client_ip: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = {
            "ApiUser": api_user,
            "ApiKey": api_key,
            "UserName": api_user,
            "ClientIp": client_ip,
        }
        # Reason: `transport` is test-only DI (httpx.MockTransport); None lets httpx use the network.
        self._transport = transport
        # Reason: setHosts replaces every record, so two overlapping read-modify-writes
        # would drop one of them. One writer at a time within this process.
        self._write_lock = asyncio.Lock()

    async def list_records(self, domain: str) -> list[DnsRecord]:
        """Every host record on the domain."""
        root = await self._call(GET_HOSTS, _domain_fields(domain))
        return [
            DnsRecord(
                host=host.attrib["Name"],
                type=RecordType(host.attrib["Type"]),
                address=host.attrib["Address"],
                ttl=int(host.attrib["TTL"]),
                mx_pref=int(host.attrib["MXPref"]),
            )
            for host in root.iterfind(".//nc:DomainDNSGetHostsResult/nc:host", NS)
        ]

    async def upsert_record(self, domain: str, record: DnsRecord) -> None:
        """Set `record`, replacing one with the same host and type, keeping the rest."""
        async with self._write_lock:
            current = await self.list_records(domain)
            kept = [
                r for r in current if (r.host, r.type) != (record.host, record.type)
            ]
            await self._set_records(domain, [*kept, record])

    async def _set_records(self, domain: str, records: list[DnsRecord]) -> None:
        fields = _domain_fields(domain)
        for n, r in enumerate(records, start=1):
            fields[f"HostName{n}"] = r.host
            fields[f"RecordType{n}"] = r.type.value
            fields[f"Address{n}"] = r.address
            fields[f"MXPref{n}"] = str(r.mx_pref)
            fields[f"TTL{n}"] = str(r.ttl)
        # Reason: Namecheap drops MX hosts unless the domain's mail setting is custom MX.
        if any(r.type == RecordType.MX for r in records):
            fields["EmailType"] = "MX"
        await self._call(SET_HOSTS, fields)

    async def _call(self, command: str, fields: dict[str, str]) -> ET.Element:
        async with httpx.AsyncClient(transport=self._transport) as http:
            response = await http.post(
                API_URL, data={**self._auth, "Command": command, **fields}
            )
        response.raise_for_status()
        # Namecheap's own response, not user input.
        root = ET.fromstring(response.text)  # noqa: S314  # nosec B314
        if root.attrib.get("Status") != "OK":
            errors = "; ".join(e.text or "" for e in root.iterfind(".//nc:Error", NS))
            raise RuntimeError(f"namecheap {command} failed: {errors}")
        return root


def _domain_fields(domain: str) -> dict[str, str]:
    """Namecheap wants the domain split: SLD=arcnode, TLD=io."""
    sld, tld = domain.split(".", 1)
    return {"SLD": sld, "TLD": tld}
