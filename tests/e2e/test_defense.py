"""Real-AWS e2e — defense (Neptune+AOSS+Aurora) leg.

Three signals end-to-end:
1. /health 200 — proves `python -m python_mcp_server seed` completed
   (Neptune Bulk Loader + AOSS index populate). If cfg.graph block didn't
   reach mcp-server, seed raises and health never becomes reachable.
2. GET /sites/{site_id}/measurements — proves gateway publishes → broker
   → telemetry-writer → Aurora pg_partman, and analyst-server reads back.
3. POST /analyst/chat — proves graphiti.search returns rows on Neptune.
   Uses Bedrock (Sonnet 4.6 via cross-region inference); ~$0.01/chat.

Gated by RUN_DEFENSE_E2E=1 — Neptune+AOSS cost ~$1-2/run.
"""

from __future__ import annotations

import json as json_lib
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
import urllib3

# Explicit fixture imports — no conftest.py auto-discovery. defense_stack
# pulls in cfn + defense_site_id transitively.
from .fixtures import cfn, defense_site_id, defense_stack  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DEFENSE_E2E") != "1",
    reason="defense e2e is on-demand only (Neptune+AOSS cost)",
)

HEALTH_TIMEOUT_S: Final[int] = 600
HEALTH_POLL_S: Final[int] = 15
# After /health passes, give the gateway time to connect to all mock
# protocols + publish a few cycles before reading measurements back.
TELEMETRY_SETTLE_S: Final[int] = 60


def _http() -> urllib3.PoolManager:
    return urllib3.PoolManager()


def _wait_for_health(public_ip: str) -> None:
    """Poll analyst-server /health until 200 or HEALTH_TIMEOUT_S."""
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
def test_defense_health_proves_mcp_seed_completed(
    defense_stack: dict[str, str],
) -> None:
    """analyst-server's /health == 200 only after `mcp-server seed` finishes.

    Seed runs Neptune Bulk Loader + AOSS bulk-populate; both require the
    NeptuneGraph cfg block (analyst-cfg.customer.yml written by UserData).
    """
    _wait_for_health(defense_stack["public_ip"])


@pytest.mark.e2e
def test_defense_telemetry_persists_to_aurora(
    defense_stack: dict[str, str],
) -> None:
    """Gateway → MQTT → telemetry-writer → Aurora.

    Reads back through analyst-server's GET /measurements so the test
    doesn't need direct VPC-private Aurora access. Single-site deploy:
    the server knows its own site_id from cfg — no site path segment.
    """
    public_ip = defense_stack["public_ip"]
    _wait_for_health(public_ip)
    time.sleep(TELEMETRY_SETTLE_S)

    # 5min window so even a slow first publish lands in range. ISO with
    # a `Z` suffix — Z is alphanumeric so it survives the query string
    # untouched, unlike a `+00:00` offset where `+` decodes to space.
    now = datetime.now(UTC)
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"http://{public_ip}:8000/measurements"
        f"?device_id=meter_01&measurement=kwh_delivered&start={start}&end={end}"
    )
    resp = _http().request("GET", url, timeout=urllib3.Timeout(connect=5, read=15))
    assert resp.status == 200, f"unexpected status {resp.status}: {resp.data!r}"
    body = resp.json()
    points = body.get("points", [])
    non_null = [p for p in points if p.get("value") is not None]
    assert non_null, f"no non-null points in 5min window: {body!r}"


@pytest.mark.e2e
def test_defense_graph_chat_returns_assistant_message(
    defense_stack: dict[str, str],
) -> None:
    """POST /analyst/chat with a graph-flavored question.

    Proves graphiti.search returns rows on the seeded Neptune cluster
    AND the agent can synthesize an answer with Bedrock Sonnet 4.6.
    """
    public_ip = defense_stack["public_ip"]
    _wait_for_health(public_ip)

    body = {
        "conversationId": str(uuid.uuid4()),
        "message": "What does the protective relay protect against?",
        "context": {"siteId": defense_stack["site_id"]},
    }
    resp = _http().request(
        "POST",
        f"http://{public_ip}:8000/analyst/chat",
        body=json_lib.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        timeout=urllib3.Timeout(connect=5, read=120),  # LLM call up to ~90s
    )
    assert resp.status == 200, f"unexpected status {resp.status}: {resp.data!r}"
    msg = resp.json()
    # AnalystMessage shape: role=assistant, content=[{type:text,text:"..."}]
    assert msg.get("role") == "assistant", msg
    text_parts = [
        c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text"
    ]
    assert any(t.strip() for t in text_parts), f"empty assistant text: {msg!r}"


# ─── HMI/broker parity with the commercial leg ──────────────────────────
# Same containers, same contracts — the checks are shared (hmi_checks.py).
# Import here (not top) keeps the original defense tests' imports untouched.
from .hmi_checks import (  # noqa: E402
    check_anonymous_rejected,
    check_browser_dispatch_settles,
    check_browser_login_sld,
    check_dispatch_round_trip,
    check_login_cred_exchange,
    check_spa_and_runtime_config,
    check_viewer_receives_telemetry,
)


@pytest.mark.e2e
def test_defense_hmi_serves_spa_and_runtime_config(
    defense_stack: dict[str, str],
) -> None:
    check_spa_and_runtime_config(defense_stack)


@pytest.mark.e2e
def test_defense_login_exchanges_for_role_broker_credential(
    defense_stack: dict[str, str],
) -> None:
    check_login_cred_exchange(defense_stack)


@pytest.mark.e2e
def test_defense_anonymous_broker_connection_is_rejected(
    defense_stack: dict[str, str],
) -> None:
    check_anonymous_rejected(defense_stack)


@pytest.mark.e2e
def test_defense_viewer_receives_live_telemetry(
    defense_stack: dict[str, str],
) -> None:
    check_viewer_receives_telemetry(defense_stack)


@pytest.mark.e2e
def test_defense_operator_dispatch_round_trip(defense_stack: dict[str, str]) -> None:
    check_dispatch_round_trip(defense_stack)


@pytest.mark.e2e
def test_defense_browser_login_then_live_sld(defense_stack: dict[str, str]) -> None:
    check_browser_login_sld(defense_stack)


@pytest.mark.e2e
def test_defense_browser_operator_dispatch_settles(
    defense_stack: dict[str, str],
) -> None:
    check_browser_dispatch_settles(defense_stack)
