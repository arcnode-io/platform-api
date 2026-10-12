"""The rate limit keys on the client Caddy saw. Only the entry Caddy appended is trusted."""

from src.orders.client_address import client_address


def test_the_rightmost_forwarded_entry_is_the_client() -> None:
    """A client can prepend anything to X-Forwarded-For; Caddy appends the real address last."""
    # Arrange + Act
    actual = client_address("9.9.9.9, 203.0.113.7", fallback="10.0.0.1")

    # Assert
    assert actual == "203.0.113.7"


def test_without_a_forwarded_header_the_socket_address_is_used() -> None:
    assert client_address(None, fallback="10.0.0.1") == "10.0.0.1"


def test_with_neither_there_is_still_one_shared_bucket() -> None:
    assert client_address(None, fallback=None) == "unknown"
