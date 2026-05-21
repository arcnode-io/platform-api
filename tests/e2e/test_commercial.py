"""Real-AWS e2e — commercial broker leg.

Scenarios live as separate test fns so failures point at the broken
contract directly. Each gets its own fresh stack (session-scoped CFN
client, function-scoped stack) so concurrent CI runs don't poison
each other.

Run: ``uv run pytest -m e2e``
"""

from __future__ import annotations

import json as json_lib
import time
import uuid

import psycopg2
import psycopg2.extensions
import pytest
import urllib3

# Explicit fixture imports — no conftest.py auto-discovery. commercial_stack
# pulls in cfn/aura_url/tiger_url/site_id transitively, so all must be in
# scope here for pytest's resolver.
from .fixtures import (  # noqa: F401
    aura_url,
    cfn,
    commercial_stack,
    site_id,
    tiger_conn,
    tiger_url,
)

POST_BOOT_SETTLE_S = 60
ROW_COUNT_SQL = "SELECT COUNT(*) FROM measurements WHERE site_id = %s"
DELETE_FOR_SITE_SQL = "DELETE FROM measurements WHERE site_id = %s"
HEALTH_TIMEOUT_S = 600
HEALTH_POLL_S = 15


def _http() -> urllib3.PoolManager:
    return urllib3.PoolManager()


def _wait_for_health(public_ip: str) -> None:
    url = f"http://{public_ip}:8000/health"
    http = _http()
    deadline = time.time() + HEALTH_TIMEOUT_S
    last_err: str | None = None
    while time.time() < deadline:
        try:
            resp = http.request("GET", url, timeout=urllib3.Timeout(connect=5, read=5))
            if resp.status == 200:
                return
            last_err = f"http {resp.status}"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(HEALTH_POLL_S)
    pytest.fail(f"/health never returned 200 within {HEALTH_TIMEOUT_S}s: {last_err}")


@pytest.mark.e2e
def test_fixtures_e2e_publishes_to_tiger(
    commercial_stack: dict[str, str],
    tiger_conn: psycopg2.extensions.connection,
) -> None:
    """Full path: gateway → mocks → MQTT → telemetry-writer → Tiger.

    industrial-fixtures DTM points devices at the mock-* compose
    services. Within ~60s of CREATE_COMPLETE the gateway has connected
    via real protocols and rows should be landing.
    """
    # Arrange — let containers settle past initial race
    time.sleep(POST_BOOT_SETTLE_S)
    site_id = commercial_stack["site_id"]

    # Act
    with tiger_conn.cursor() as cur:
        cur.execute(ROW_COUNT_SQL, (site_id,))
        count = cur.fetchone()[0]
        # Clean up so the Tiger test DB doesn't accumulate per-pipeline cruft
        cur.execute(DELETE_FOR_SITE_SQL, (site_id,))
        tiger_conn.commit()

    # Assert
    assert count > 0, f"no rows from site_id={site_id} — broker leg broken"


@pytest.mark.e2e
def test_commercial_graph_chat_returns_assistant_message(
    commercial_stack: dict[str, str],
) -> None:
    """POST /analyst/chat — proves graphiti.search returns rows on Aura
    and the agent synthesizes an answer with Bedrock Sonnet 4.6.
    """
    public_ip = commercial_stack["public_ip"]
    _wait_for_health(public_ip)

    body = {
        "conversationId": str(uuid.uuid4()),
        "message": "What does the protective relay protect against?",
        "context": {"siteId": commercial_stack["site_id"]},
    }
    resp = _http().request(
        "POST",
        f"http://{public_ip}:8000/analyst/chat",
        body=json_lib.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        timeout=urllib3.Timeout(connect=5, read=120),
    )
    assert resp.status == 200, f"unexpected status {resp.status}: {resp.data!r}"
    msg = resp.json()
    assert msg.get("role") == "assistant", msg
    text_parts = [
        c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text"
    ]
    assert any(t.strip() for t in text_parts), f"empty assistant text: {msg!r}"
