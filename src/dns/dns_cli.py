"""One-off DNS edits on arcnode.io from a whitelisted box.

    NAMECHEAP_API_KEY=... uv run python -m src.dns.dns_cli list --domain arcnode.io
    NAMECHEAP_API_KEY=... uv run python -m src.dns.dns_cli upsert --domain arcnode.io \
        --host platform --type A --address 1.2.3.4 --ttl 60

The key comes from the environment, never argv. The caller's public address is
looked up because Namecheap checks it against the account's whitelist.
"""

import argparse
import asyncio
import logging
import os
from typing import Final

import httpx

from src.dns.dns_client import DnsClient, DnsRecord, RecordType

API_USER: Final[str] = "iotresister"
API_KEY_ENV: Final[str] = "NAMECHEAP_API_KEY"
CHECK_IP_URL: Final[str] = "https://checkip.amazonaws.com"


async def _public_ip() -> str:
    async with httpx.AsyncClient() as http:
        return (await http.get(CHECK_IP_URL)).text.strip()


async def _run(args: argparse.Namespace) -> None:
    client = DnsClient(
        api_user=API_USER,
        api_key=os.environ[API_KEY_ENV],
        client_ip=await _public_ip(),
    )
    if args.command == "upsert":
        await client.upsert_record(
            args.domain,
            DnsRecord(
                host=args.host,
                type=RecordType(args.type),
                address=args.address,
                ttl=args.ttl,
            ),
        )
    for record in await client.list_records(args.domain):
        logging.info("%s", record)


def main() -> None:
    """Parse the command line and run it."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--domain", required=True)
    upsert = sub.add_parser("upsert")
    upsert.add_argument("--domain", required=True)
    upsert.add_argument("--host", required=True)
    upsert.add_argument("--type", required=True, choices=[t.value for t in RecordType])
    upsert.add_argument("--address", required=True)
    upsert.add_argument("--ttl", type=int, default=1800)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
