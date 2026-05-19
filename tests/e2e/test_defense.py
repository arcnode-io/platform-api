"""Real-AWS e2e — defense (Neptune+AOSS) leg.

Proves the Phase B cfg.graph block reaches a running mcp-server. /health
returns 200 only after the Dockerfile's `python -m python_mcp_server seed
&& uv run -m src.main` chain completes — seed loads Neptune via Bulk Loader
+ AOSS via opensearch bulk, which both need NeptuneGraph cfg resolved
from analyst-cfg.customer.yml (written by UserData).

Gated by RUN_DEFENSE_E2E=1 so the nightly cron stays cheap. Trigger
on demand:
    glab api -X POST 'projects/.../pipeline' \\
        --field 'variables[][key]=RUN_DEFENSE_E2E' \\
        --field 'variables[][value]=1' \\
        --field 'ref=main'

Run: ``RUN_DEFENSE_E2E=1 uv run pytest -m e2e tests/e2e/test_defense.py``
"""

from __future__ import annotations

import os
import time

import pytest
import urllib3

# Defense smokes only on demand — Neptune+AOSS cost ~$1-2/run.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DEFENSE_E2E") != "1",
    reason="defense e2e is on-demand only (Neptune+AOSS cost)",
)

HEALTH_TIMEOUT_S = 600  # 10min — analyst-server boots after Neptune seed completes
HEALTH_POLL_S = 15


@pytest.mark.e2e
def test_defense_health_proves_mcp_seed_completed(
    defense_stack: dict[str, str],
) -> None:
    """analyst-server's /health == 200 only after `mcp-server seed` finishes.

    Seed runs Neptune Bulk Loader + AOSS bulk-populate; both require the
    NeptuneGraph cfg block (analyst-cfg.customer.yml written by UserData).
    If Phase B's wiring broke, seed raises and the container restarts
    forever — /health never becomes reachable within the timeout.
    """
    # Arrange
    url = f"http://{defense_stack['public_ip']}:8000/health"
    http = urllib3.PoolManager()
    deadline = time.time() + HEALTH_TIMEOUT_S

    # Act + Assert — poll until 200 or timeout
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
