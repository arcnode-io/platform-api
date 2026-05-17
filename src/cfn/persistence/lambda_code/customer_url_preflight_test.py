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
