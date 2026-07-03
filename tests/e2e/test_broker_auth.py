"""Real-AWS e2e — the v1 broker-auth chain through the deployed HMI
(commercial variant). Assertion bodies live in hmi_checks.py and run
identically against the defense stack from test_defense.py.

Run: ``uv run pytest -m e2e tests/e2e/test_broker_auth.py``
"""

from __future__ import annotations

import pytest

# Explicit fixture imports — no conftest. commercial_stack pulls cfn / aura_url
# / tiger_url / commercial_site_id transitively, so all must be in scope.
from .fixtures import (  # noqa: F401
    aura_url,
    cfn,
    commercial_site_id,
    commercial_stack,
    tiger_url,
)
from .hmi_checks import (
    check_anonymous_rejected,
    check_dispatch_round_trip,
    check_login_cred_exchange,
    check_spa_and_runtime_config,
    check_viewer_receives_telemetry,
)


@pytest.mark.e2e
def test_hmi_serves_spa_and_runtime_config(commercial_stack: dict[str, str]) -> None:
    check_spa_and_runtime_config(commercial_stack)


@pytest.mark.e2e
def test_login_exchanges_for_role_broker_credential(
    commercial_stack: dict[str, str],
) -> None:
    check_login_cred_exchange(commercial_stack)


@pytest.mark.e2e
def test_anonymous_broker_connection_is_rejected(
    commercial_stack: dict[str, str],
) -> None:
    check_anonymous_rejected(commercial_stack)


@pytest.mark.e2e
def test_authenticated_viewer_receives_live_telemetry(
    commercial_stack: dict[str, str],
) -> None:
    check_viewer_receives_telemetry(commercial_stack)


@pytest.mark.e2e
def test_operator_dispatch_round_trip(commercial_stack: dict[str, str]) -> None:
    check_dispatch_round_trip(commercial_stack)
