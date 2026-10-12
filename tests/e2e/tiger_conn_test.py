"""The Tiger connection fails loudly instead of waiting forever on a stalled socket."""

import pytest

from tests.e2e import fixtures


def test_tiger_connection_has_a_connect_timeout_statement_timeout_and_keepalives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    seen: dict[str, object] = {}

    class FakeConn:
        def close(self) -> None:
            seen["closed"] = True

    def fake_connect(dsn: str, **kwargs: object) -> FakeConn:
        seen["dsn"] = dsn
        seen.update(kwargs)
        return FakeConn()

    monkeypatch.setattr(fixtures.psycopg2, "connect", fake_connect)

    # Act
    fixtures.connect_tiger("postgres://x")

    # Assert
    assert seen["connect_timeout"] == fixtures.TIGER_CONNECT_TIMEOUT_S
    assert seen["keepalives"] == 1
    assert seen["keepalives_idle"] == fixtures.TIGER_KEEPALIVE_IDLE_S
    options = str(seen["options"])
    assert f"statement_timeout={fixtures.TIGER_STATEMENT_TIMEOUT_MS}" in options
