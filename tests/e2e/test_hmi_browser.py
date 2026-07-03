"""Real-AWS browser e2e — Chromium against the deployed HMI (commercial
variant). Assertion bodies live in hmi_checks.py and run identically against
the defense stack from test_defense.py. Needs `playwright install chromium`.

Run: ``uv run pytest -m e2e tests/e2e/test_hmi_browser.py``
"""

from __future__ import annotations

import pytest

from .fixtures import (  # noqa: F401
    aura_url,
    cfn,
    commercial_site_id,
    commercial_stack,
    tiger_url,
)
from .hmi_checks import check_browser_dispatch_settles, check_browser_login_sld


@pytest.mark.e2e
def test_browser_login_then_live_sld(commercial_stack: dict[str, str]) -> None:
    check_browser_login_sld(commercial_stack)


@pytest.mark.e2e
def test_browser_operator_dispatch_settles(commercial_stack: dict[str, str]) -> None:
    check_browser_dispatch_settles(commercial_stack)
