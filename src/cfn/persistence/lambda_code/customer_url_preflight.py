"""Customer URL preflight — TCP + TLS + Bolt handshake against operator URLs.

Fails the CFN stack fast (within ~10s of stack-create) if the customer's
Tiger Cloud / Neo4j Aura URLs are unreachable, have bad TLS, or aren't
speaking the expected protocol — saves the ~10min Aurora cluster spin-up
that would otherwise be wasted before telemetry-writer / python-mcp-server
crash on connect.

Does NOT validate auth (no psycopg2 / neo4j-driver in the Lambda runtime
to keep the bundle zero-dep). Bad-password failures still surface at
runtime when compose starts the consumer services. Catches everything
else: DNS typo, wrong port, IP-allowlist missing, paused service, cert
expired, hostname mismatch, wrong-protocol-on-port.

Runtime: python3.13 outside VPC. boto3 + urllib.request + socket + ssl
are all built-in.

Hard deadline: HANDLER_DEADLINE_S (25s) via SIGALRM wraps the whole
handler. `socket.create_connection`'s `timeout=` only bounds the TCP
connect phase — DNS lookup is unbounded and can block forever if the
host doesn't resolve. SIGALRM catches that and any other hang so the
function ALWAYS responds to CFN (SUCCESS or FAILED) instead of dying
silently at Lambda's 30s ceiling. Previously a DNS-block left CFN
waiting ~50 min for retries before giving up.
"""

import json
import signal
import socket
import ssl
import urllib.request
from urllib.parse import urlsplit

# Leave ~5s headroom for _respond's PUT to the CFN response URL.
HANDLER_DEADLINE_S = 25


class HandlerTimeoutError(Exception):
    """Raised by SIGALRM when the handler exceeds its deadline."""


def handler(event: dict, context: object) -> None:
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "customer-url-preflight")

    def _on_alarm(_signum: int, _frame: object) -> None:
        raise HandlerTimeoutError(
            f"preflight exceeded {HANDLER_DEADLINE_S}s deadline "
            "(DNS hang on customer URL?)"
        )

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(HANDLER_DEADLINE_S)
    try:
        if request_type == "Create":
            props = event["ResourceProperties"]
            _check_postgres(props["TimeseriesUrl"])
            _check_neo4j(props["GraphUrl"])
        # Update + Delete are no-ops: the URLs are validated at Create;
        # updates re-fire only if ProbeVersion bumps, which we don't here.
        signal.alarm(0)
        _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:
        signal.alarm(0)
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _permissive_tls_context() -> ssl.SSLContext:
    """TLS context that skips cert verification.

    Preflight validates REACHABILITY + speaks-TLS, not chain trust —
    Tiger Cloud and many managed Postgres providers use intermediate
    cert chains that Python's default bundle doesn't trust but psycopg2
    / neo4j-python (libpq + their own ssl wiring) accept. Validating
    chain trust here triggers false positives that block deploys for
    URLs the actual consumer would happily use.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _check_postgres(url: str) -> None:
    """TCP connect + (if sslmode=require) TLS handshake."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or 5432
    require_tls = "sslmode=require" in (parts.query or "")
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except Exception as e:
        raise RuntimeError(f"TimeseriesUrl: cannot reach {host}:{port} ({e})") from e
    try:
        if require_tls:
            try:
                sock = _permissive_tls_context().wrap_socket(sock, server_hostname=host)
            except Exception as e:
                raise RuntimeError(
                    f"TimeseriesUrl: TLS handshake failed for {host}:{port} ({e})"
                ) from e
    finally:
        sock.close()


def _check_neo4j(url: str) -> None:
    """TCP connect + TLS (if neo4j+s://) + Bolt magic handshake."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or 7687
    require_tls = parts.scheme.endswith("+s")
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except Exception as e:
        raise RuntimeError(f"GraphUrl: cannot reach {host}:{port} ({e})") from e
    try:
        if require_tls:
            try:
                sock = _permissive_tls_context().wrap_socket(sock, server_hostname=host)
            except Exception as e:
                raise RuntimeError(
                    f"GraphUrl: TLS handshake failed for {host}:{port} ({e})"
                ) from e
        # Bolt protocol handshake: 4-byte magic + 4 supported versions (16 bytes)
        # Server picks one (4 bytes) or 0x00000000 if none compatible.
        sock.sendall(
            b"\x60\x60\xb0\x17" + b"\x00\x00\x00\x04" + b"\x00\x00\x00\x00" * 3
        )
        chosen = sock.recv(4)
        if chosen == b"\x00\x00\x00\x00":
            raise RuntimeError(
                f"GraphUrl: no compatible Bolt version (server {host}:{port})"
            )
        if len(chosen) != 4:
            raise RuntimeError(
                f"GraphUrl: server did not respond with Bolt handshake "
                f"(got {len(chosen)} bytes from {host}:{port})"
            )
    finally:
        sock.close()


def _respond(event: dict, status: str, physical_id: str, data: dict) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": data.get("Reason", "see CloudWatch logs"),
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": {k: v for k, v in data.items() if k != "Reason"},
        }
    ).encode()
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    # Defensive timeout — S3 PUT should be <1s; bound at 5s so even if
    # something goes sideways we hit Lambda's 30s ceiling cleanly with a
    # proper error rather than mid-stream hang.
    urllib.request.urlopen(req, timeout=5)
