"""Real-AWS browser e2e — drive the deployed HMI through a real Chromium.

Where test_broker_auth.py proves the auth + data chain at the HTTP/MQTT level,
this proves it at the *pixel* level: a real browser loads the deployed SPA,
logs in through the login page fe shipped, and renders live gateway telemetry
(SLD canvas) over the same-origin broker proxy.

Uses fe's data-testids (login-username / login-password / login-submit,
sld-canvas, dispatch-apply / dispatch-status). Marked @pytest.mark.e2e →
deselected from the normal suite; runs in the manual e2e job against a real
deploy. Needs `playwright install chromium`.

Run: ``uv run pytest -m e2e tests/e2e/test_hmi_browser.py``
"""

from __future__ import annotations

import time

import pytest
import urllib3
from playwright.sync_api import expect, sync_playwright

from .fixtures import (  # noqa: F401
    E2E_OPERATOR_PW,
    E2E_VIEWER_PW,
    aura_url,
    cfn,
    commercial_site_id,
    commercial_stack,
    tiger_url,
)

HMI_TIMEOUT_S = 600
HMI_POLL_S = 15
OPERATOR = ("operator", E2E_OPERATOR_PW)


def _wait_for_hmi(public_ip: str) -> None:
    http = urllib3.PoolManager()
    deadline = time.time() + HMI_TIMEOUT_S
    last = ""
    while time.time() < deadline:
        try:
            r = http.request(
                "GET",
                f"http://{public_ip}/",
                timeout=urllib3.Timeout(connect=5, read=5),
            )
            if r.status == 200:
                return
            last = f"http {r.status}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(HMI_POLL_S)
    pytest.fail(f"HMI never served :80 within {HMI_TIMEOUT_S}s: {last}")


@pytest.mark.e2e
def test_browser_login_then_live_sld(commercial_stack: dict[str, str]) -> None:
    """Real Chromium: load the deployed SPA → login → the app shell renders
    and the SLD canvas paints from live broker telemetry."""
    # Arrange
    ip = commercial_stack["public_ip"]
    _wait_for_hmi(ip)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            # Act — load + log in via the shipped login page.
            page.goto(f"http://{ip}/", wait_until="domcontentloaded")
            page.get_by_test_id("login-username").fill(OPERATOR[0])
            page.get_by_test_id("login-password").fill(OPERATOR[1])
            page.get_by_test_id("login-submit").click()

            # Assert — login gate clears (we're into the app shell).
            expect(page.get_by_test_id("login-submit")).to_be_hidden(timeout=15_000)

            # Act — navigate to the single-line diagram (default screen is
            # Overview; SLD is its own route /modules/sld). SPA route, served
            # via nginx history-fallback.
            page.goto(f"http://{ip}/modules/sld", wait_until="domcontentloaded")

            # Assert — the SLD canvas mounts (topology rendered from the broker).
            expect(page.get_by_test_id("sld-canvas")).to_be_visible(timeout=20_000)
        finally:
            browser.close()
