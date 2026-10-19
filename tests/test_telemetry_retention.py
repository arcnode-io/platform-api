"""Integration tests for telemetry-writer's retention: real TimescaleDB and plain Postgres."""

import importlib.util
from pathlib import Path
from types import ModuleType

import psycopg2
import pytest

from tests.fixtures.containers import start_postgres

WRITER_PATH = (
    Path(__file__).parent.parent
    / "src"
    / "compose"
    / "init-scripts"
    / "telemetry_writer.py"
)
# Same major as the on-prem box (src/iso/phases/postgres.sh installs PG17 + TimescaleDB 2).
TIMESCALE_IMAGE = "timescale/timescaledb:2.17.2-pg17"


def _load_writer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("telemetry_writer", WRITER_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _retention_jobs(url: str) -> list[str]:
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT config->>'drop_after' FROM timescaledb_information.jobs "
            "WHERE proc_name = 'policy_retention' AND hypertable_name = 'measurements'"
        )
        return [row[0] for row in cur.fetchall()]


def test_the_writer_keeps_the_customers_window_on_timescale() -> None:
    """Changing the window replaces the policy instead of adding a second one."""
    # Arrange
    writer = _load_writer()
    with start_postgres(password="test", image=TIMESCALE_IMAGE) as pg:
        conn = psycopg2.connect(pg.url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        writer.bootstrap_schema(conn)

        # Act
        writer.apply_retention(conn, 7)
        first = _retention_jobs(pg.url)
        writer.apply_retention(conn, 3)
        second = _retention_jobs(pg.url)
        conn.close()

    # Assert
    assert first == ["7 days"]
    assert second == ["3 days"]


def test_the_writer_refuses_a_database_it_cannot_clean() -> None:
    """No TimescaleDB and no pg_partman means old rows would pile up until the disk fills."""
    # Arrange
    writer = _load_writer()
    with start_postgres(password="test", image="postgres:17") as pg:
        conn = psycopg2.connect(pg.url)
        conn.autocommit = True
        writer.bootstrap_schema(conn)

        # Act / Assert
        with pytest.raises(RuntimeError, match="retention"):
            writer.apply_retention(conn, 7)
        conn.close()
