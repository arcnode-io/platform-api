"""Real-AWS e2e — the v1 broker-auth chain through the deployed HMI.

Proves the flip end to end on a real stack: the HMI's nginx serves the SPA +
runtime config, login returns a JWT, that token exchanges for a role-scoped
broker credential, and the credential authenticates an MQTT-over-WebSocket
connection through the same-origin ``/mqtt`` proxy — while anonymous is
rejected and authenticated viewers receive live gateway telemetry.

Complements ``test_commercial.py`` (which covers gateway→Tiger persistence +
analyst chat). Together they are the full broker-leg e2e. Manual / on-demand —
each shares the session-scoped ``commercial_stack`` (one real CFN deploy).

Run: ``uv run pytest -m e2e tests/e2e/test_broker_auth.py``
"""

from __future__ import annotations

import json as json_lib
import threading
import time

import paho.mqtt.client as mqtt
import pytest
import urllib3

# Explicit fixture imports — no conftest. commercial_stack pulls cfn / aura_url
# / tiger_url / commercial_site_id transitively, so all must be in scope.
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


@pytest.mark.e2e
def test_hmi_serves_spa_and_runtime_config(commercial_stack: dict[str, str]) -> None:
    """nginx serves the SPA and the runtime overlay (alias) with the real
    site id — without it the deployed SPA can't learn its deployment."""
    # Arrange
    ip = commercial_stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    spa = _http().request("GET", f"http://{ip}/", timeout=urllib3.Timeout(read=10))
    cfg = _http().request(
        "GET", f"http://{ip}/cfg.customer.yml", timeout=urllib3.Timeout(read=10)
    )

    # Assert
    assert spa.status == 200
    assert cfg.status == 200, "nginx alias /cfg.customer.yml not served"
    assert commercial_stack["site_id"] in cfg.data.decode()


@pytest.mark.e2e
def test_login_exchanges_for_role_broker_credential(
    commercial_stack: dict[str, str],
) -> None:
    """login → JWT → /mqtt-credentials returns the operator's File-RBAC user;
    the broker password never sits in the bundle, only behind auth."""
    # Arrange
    ip = commercial_stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    token = _login(ip, "operator", E2E_OPERATOR_PW)
    cred = _mqtt_credentials(ip, token)

    # Assert
    assert cred["username"] == "arcnode_operator"
    assert len(cred["password"]) >= 16


@pytest.mark.e2e
def test_anonymous_broker_connection_is_rejected(
    commercial_stack: dict[str, str],
) -> None:
    """File RBAC must refuse an anonymous MQTT-over-WS connect (rc != 0)."""
    # Arrange
    ip = commercial_stack["public_ip"]
    _wait_for_hmi(ip)

    # Act
    rc = _broker_connect_rc(ip, None, None)

    # Assert — 0 would mean the broker accepted anonymous (auth bypassed)
    assert rc != 0, "anonymous broker connect was accepted — File RBAC bypassed"


@pytest.mark.e2e
def test_authenticated_viewer_receives_live_telemetry(
    commercial_stack: dict[str, str],
) -> None:
    """The whole live-gauge path: login as viewer → fetch broker cred →
    connect over the nginx /mqtt proxy → receive a real gateway measurement.
    """
    # Arrange
    ip = commercial_stack["public_ip"]
    site = commercial_stack["site_id"]
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
