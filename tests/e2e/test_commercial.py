"""Real-AWS e2e — commercial broker leg.

Scenarios live as separate test fns so failures point at the broken
contract directly. Each gets its own fresh stack (session-scoped CFN
client, function-scoped stack) so concurrent CI runs don't poison
each other.

Run: ``uv run pytest -m e2e``
"""

from __future__ import annotations

import time

import psycopg2
import psycopg2.extensions
import pytest

POST_BOOT_SETTLE_S = 60
ROW_COUNT_SQL = "SELECT COUNT(*) FROM measurements WHERE site_id = %s"
DELETE_FOR_SITE_SQL = "DELETE FROM measurements WHERE site_id = %s"


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
