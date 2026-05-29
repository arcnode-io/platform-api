"""Tests for the customer-URL preflight Lambda source.

Pure-Python parts — handler callable, URL parsing, error message shape.
TCP/TLS side effects covered via a localhost listener (no network).
"""

import importlib.util
import socket
import threading
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent / "customer_url_preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("customer_url_preflight", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    """Lambda entry point must be ``handler(event, context)``."""
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert callable(mod.handler)


def test_check_postgres_passes_against_open_tcp() -> None:
    """No sslmode=require → plain TCP connect is enough."""
    # Arrange
    mod = _load_module()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)

    def _accept_and_close() -> None:
        conn, _ = sock.accept()
        conn.close()

    threading.Thread(target=_accept_and_close, daemon=True).start()

    # Act + Assert — no exception
    mod._check_postgres(f"postgres://u:p@127.0.0.1:{port}/db")
    sock.close()


def test_check_postgres_raises_on_unreachable() -> None:
    """Refused connect produces a TimeseriesUrl-prefixed error."""
    # Arrange
    mod = _load_module()

    # Act + Assert — port 1 is reserved, expect connection refused
    with pytest.raises(RuntimeError, match=r"TimeseriesUrl: cannot reach"):
        mod._check_postgres("postgres://u:p@127.0.0.1:1/db")


def test_check_neo4j_raises_on_unreachable() -> None:
    """Refused connect produces a GraphUrl-prefixed error."""
    # Arrange
    mod = _load_module()

    # Act + Assert
    with pytest.raises(RuntimeError, match=r"GraphUrl: cannot reach"):
        mod._check_neo4j("neo4j://u:p@127.0.0.1:1")


def test_handler_responds_failed_when_deadline_exceeds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """SIGALRM-based handler deadline catches network hangs and FAILS to
    CFN within the deadline + ~1s, instead of letting Lambda time out at
    30s silently.

    Patches HANDLER_DEADLINE_S to 1s and forces _check_postgres to sleep
    longer than that — handler must call _respond with FAILED before the
    sleep finishes.
    """
    import time

    mod = _load_module()
    mod.HANDLER_DEADLINE_S = 1  # tighten for fast test

    def _hang_postgres(_url: str) -> None:
        time.sleep(5)  # simulate DNS hang or unreachable host

    monkeypatch.setattr(mod, "_check_postgres", _hang_postgres)

    captured: dict[str, object] = {}

    def _capture_respond(
        event: dict, status: str, physical_id: str, data: dict
    ) -> None:
        captured["status"] = status
        captured["reason"] = data.get("Reason", "")

    monkeypatch.setattr(mod, "_respond", _capture_respond)

    start = time.time()
    mod.handler(
        {
            "RequestType": "Create",
            "StackId": "s",
            "RequestId": "r",
            "LogicalResourceId": "l",
            "ResponseURL": "https://example.invalid/",
            "ResourceProperties": {"TimeseriesUrl": "x", "GraphUrl": "y"},
        },
        object(),
    )
    elapsed = time.time() - start

    assert captured["status"] == "FAILED", "deadline should produce FAILED"
    assert "deadline" in str(captured.get("reason", "")).lower()
    # Deadline 1s + SIGALRM overhead < 2s; way under hang's 5s sleep.
    assert elapsed < 3.0, f"handler took {elapsed:.1f}s — deadline not bounding"


def test_check_neo4j_validates_bolt_handshake() -> None:
    """Server must respond with 4-byte chosen-version or we fail."""
    # Arrange
    mod = _load_module()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)

    def _bolt_server():
        conn, _ = sock.accept()
        try:
            conn.recv(64)  # discard the 20-byte handshake we sent
            conn.sendall(b"\x00\x00\x00\x04")  # picked version 4
        finally:
            conn.close()

    threading.Thread(target=_bolt_server, daemon=True).start()

    # Act + Assert — no exception, handshake accepted
    mod._check_neo4j(f"neo4j://u:p@127.0.0.1:{port}")
    sock.close()
