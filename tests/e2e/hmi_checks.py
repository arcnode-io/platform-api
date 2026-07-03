"""Shared deployed-HMI checks — the assertion bodies behind the broker-auth
and browser e2e, callable against ANY deployed stack (commercial or defense).

Both variants ship the identical HMI/broker/gateway containers, so parity is
one function call. Test files stay thin wrappers that pick the stack fixture;
per the no-conftest rule this is a normal module imported explicitly.
"""

from __future__ import annotations

import json as json_lib
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import pytest
import urllib3
from playwright.sync_api import expect, sync_playwright

from .fixtures import E2E_OPERATOR_PW, E2E_VIEWER_PW

HMI_TIMEOUT_S = 600
HMI_POLL_S = 15
BROKER_CONNECT_TIMEOUT_S = 15
TELEMETRY_TIMEOUT_S = 60


def _http() -> urllib3.PoolManager:
    return urllib3.PoolManager()


def _wait_for_hmi(public_ip: str) -> None:
    """Block until the HMI container's nginx answers on :80 (compose pull +
    boot lags CFN CREATE_COMPLETE by a few minutes)."""
    http = _http()
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


def _login(public_ip: str, username: str, password: str) -> str:
    """POST /api/auth/login (nginx strips /api/ → device-api /auth/login)."""
    body = json_lib.dumps({"username": username, "password": password}).encode()
    r = _http().request(
        "POST",
        f"http://{public_ip}/api/auth/login",
        body=body,
        headers={"Content-Type": "application/json"},
        timeout=urllib3.Timeout(connect=5, read=15),
    )
    # NestJS @Post returns 201 Created by default; accept either.
    assert r.status in (200, 201), f"login {username} → {r.status}: {r.data!r}"
    return r.json()["token"]


def _mqtt_credentials(public_ip: str, token: str) -> dict[str, str]:
    """GET /api/auth/mqtt-credentials with the session JWT → role broker cred."""
    r = _http().request(
        "GET",
        f"http://{public_ip}/api/auth/mqtt-credentials",
        headers={"Authorization": f"Bearer {token}"},
        timeout=urllib3.Timeout(connect=5, read=15),
    )
    assert r.status == 200, f"mqtt-credentials → {r.status}: {r.data!r}"
    return r.json()


def _broker_connect_rc(
    public_ip: str, username: str | None, password: str | None
) -> int | None:
    """Attempt an MQTT-over-WS connect through the HMI's nginx /mqtt proxy.

    Returns the CONNACK reason code (0 = success), or None if no CONNACK
    arrived. Anonymous (username=None) should be refused by File RBAC.
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path="/mqtt")
    if username is not None:
        client.username_pw_set(username, password)
    rc_box: dict[str, int] = {}
    got = threading.Event()

    def on_connect(_c, _u, _flags, reason_code, _props=None) -> None:
        rc_box["rc"] = int(reason_code.value)
        got.set()

    client.on_connect = on_connect
    try:
        client.connect(public_ip, 80, keepalive=30)
        client.loop_start()
        got.wait(BROKER_CONNECT_TIMEOUT_S)
    except Exception:
        return None
    finally:
        client.loop_stop()
        client.disconnect()
    return rc_box.get("rc")


def check_spa_and_runtime_config(stack: dict[str, str]) -> None:
    """nginx serves the SPA + the runtime overlay with the real site id."""
    # Arrange
    ip = stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    spa = _http().request("GET", f"http://{ip}/", timeout=urllib3.Timeout(read=10))
    cfg = _http().request(
        "GET", f"http://{ip}/cfg.customer.yml", timeout=urllib3.Timeout(read=10)
    )

    # Assert
    assert spa.status == 200
    assert cfg.status == 200, "nginx alias /cfg.customer.yml not served"
    assert stack["site_id"] in cfg.data.decode()


def check_login_cred_exchange(stack: dict[str, str]) -> None:
    """login → JWT → /mqtt-credentials returns the operator File-RBAC cred."""
    # Arrange
    ip = stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    token = _login(ip, "operator", E2E_OPERATOR_PW)
    cred = _mqtt_credentials(ip, token)

    # Assert
    assert cred["username"] == "arcnode_operator"
    assert len(cred["password"]) >= 16


def check_anonymous_rejected(stack: dict[str, str]) -> None:
    """File RBAC refuses an anonymous MQTT-over-WS connect."""
    # Arrange
    ip = stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    rc = _broker_connect_rc(ip, None, None)

    # Assert — 0 would mean the broker accepted anonymous (auth bypassed)
    assert rc != 0, "anonymous broker connect was accepted — File RBAC bypassed"


def check_viewer_receives_telemetry(stack: dict[str, str]) -> None:
    """viewer cred → nginx /mqtt → live gateway measurement arrives."""
    # Arrange
    ip = stack["public_ip"]
    site = stack["site_id"]
    _wait_for_hmi(ip)
    cred = _mqtt_credentials(ip, _login(ip, "viewer", E2E_VIEWER_PW))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path="/mqtt")
    client.username_pw_set(cred["username"], cred["password"])
    received: dict[str, str] = {}
    got = threading.Event()

    def on_connect(_c, _u, _flags, _rc, _props=None) -> None:
        client.subscribe(f"sites/{site}/devices/+/measurements/#")

    def on_message(_c, _u, msg) -> None:
        received["topic"] = msg.topic
        received["payload"] = msg.payload.decode()
        got.set()

    client.on_connect = on_connect
    client.on_message = on_message

    # Act
    client.connect(ip, 80, keepalive=30)
    client.loop_start()
    delivered = got.wait(TELEMETRY_TIMEOUT_S)
    client.loop_stop()
    client.disconnect()

    # Assert — a real {ts,value} envelope from the gateway, via the authed broker
    assert delivered, f"no telemetry on sites/{site}/... within {TELEMETRY_TIMEOUT_S}s"
    assert "measurements" in received["topic"]
    assert "value" in received["payload"]


def check_dispatch_round_trip(stack: dict[str, str]) -> None:
    """operator command → gateway received→done; ghost → failed+reason."""
    # Arrange
    ip = stack["public_ip"]
    site = stack["site_id"]
    _wait_for_hmi(ip)
    cred = _mqtt_credentials(ip, _login(ip, "operator", E2E_OPERATOR_PW))

    # dispatch_state is a RETAINED state topic — subscribing replays stale
    # events from prior commands, so we correlate by command_id exactly like
    # the HMI's applyDispatchEvent does. Unique per run: retained state
    # survives across e2e sessions on a shared stack.
    run_id = uuid.uuid4().hex[:8]
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path="/mqtt")
    client.username_pw_set(cred["username"], cred["password"])
    events: list[dict[str, str]] = []
    wanted: dict[str, str] = {"command_id": ""}
    got_two = threading.Event()

    def on_connect(_c, _u, _flags, _rc, _props=None) -> None:
        client.subscribe(f"sites/{site}/devices/+/events/dispatch_state", qos=1)

    def on_message(_c, _u, msg) -> None:
        event = json_lib.loads(msg.payload)
        if event.get("command_id") != wanted["command_id"]:
            return  # stale retained event from a prior command
        events.append(event)
        if len(events) >= 2:
            got_two.set()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(ip, 80, keepalive=30)
    client.loop_start()
    time.sleep(3)  # let the subscribe settle before publishing

    # Act — dispatch 1.62 MW to the DTM's BESS module.
    wanted["command_id"] = f"e2e-{run_id}-1"
    frame = {
        "ts": "2026-07-03T00:00:00Z",
        "value": 1_620_000,
        "command_id": wanted["command_id"],
    }
    client.publish(
        f"sites/{site}/devices/bess_module_01/commands/set/active_power/watts",
        json_lib.dumps(frame),
        qos=1,
    )
    delivered = got_two.wait(30)

    # Assert — received then done, correlated (contract: done = accepted).
    assert delivered, f"expected 2 acks, got {events}"
    assert [e["phase"] for e in events[:2]] == ["received", "done"]

    # Act — ghost device is rejected with a reason.
    events.clear()
    got_two.clear()
    wanted["command_id"] = f"e2e-{run_id}-2"
    frame = {
        "ts": "2026-07-03T00:00:00Z",
        "value": 5,
        "command_id": wanted["command_id"],
    }
    client.publish(
        f"sites/{site}/devices/ghost_99/commands/set/active_power/watts",
        json_lib.dumps(frame),
        qos=1,
    )
    delivered = got_two.wait(30)
    client.loop_stop()
    client.disconnect()

    # Assert
    assert delivered, f"expected 2 acks for ghost, got {events}"
    assert [e["phase"] for e in events[:2]] == ["received", "failed"]
    assert "ghost_99" in events[1].get("reason", "")


def check_browser_login_sld(stack: dict[str, str]) -> None:
    """Chromium: login page → app shell → SLD canvas renders."""
    # Arrange
    ip = stack["public_ip"]
    _wait_for_hmi(ip)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            # Act — load + log in via the shipped login page.
            page.goto(f"http://{ip}/", wait_until="domcontentloaded")
            page.get_by_test_id("login-username").fill("operator")
            page.get_by_test_id("login-password").fill(E2E_OPERATOR_PW)
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


def check_browser_dispatch_settles(stack: dict[str, str]) -> None:
    """Chromium: BESS page → Apply → confirm → status card settles off gateway acks."""
    # Arrange
    ip = stack["public_ip"]
    _wait_for_hmi(ip)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(f"http://{ip}/", wait_until="domcontentloaded")
            page.get_by_test_id("login-username").fill("operator")
            page.get_by_test_id("login-password").fill(E2E_OPERATOR_PW)
            page.get_by_test_id("login-submit").click()
            expect(page.get_by_test_id("login-submit")).to_be_hidden(timeout=15_000)

            # Act — open the dispatchable BESS module (bess_module in the
            # smoke DTM exists exactly for this test).
            page.goto(
                f"http://{ip}/devices/bess_module_01", wait_until="domcontentloaded"
            )
            apply_btn = page.get_by_test_id("dispatch-apply")
            expect(apply_btn).to_be_visible(timeout=20_000)
            apply_btn.click()
            # Two-step confirm — Apply never dispatches on first click.
            page.locator('[data-action="confirm"]').click()

            # Assert — gateway acks drive the card: received→pending,
            # done→settled. data-phase mirrors the DispatchContext phase.
            status = page.get_by_test_id("dispatch-status")
            expect(status).to_be_visible(timeout=15_000)
            expect(status).to_have_attribute("data-phase", "settled", timeout=20_000)
        finally:
            browser.close()
