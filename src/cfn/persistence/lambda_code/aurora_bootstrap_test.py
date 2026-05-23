"""Smoke tests for the Aurora bootstrap Lambda source.

The function runs in Lambda; we test what we can statically — that the
module parses, that ``handler`` is callable, and that the slice → db
mapping + extension wiring match the expected shape.
"""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "aurora_bootstrap.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aurora_bootstrap", MODULE_PATH)
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


def test_slice_specs_cover_three_variants() -> None:
    """SLICE_SPECS maps each supported slice → (db_name, app_user, extension)."""
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert set(mod.SLICE_SPECS.keys()) == {"document", "vector", "timeseries"}
    # document has no extension
    assert mod.SLICE_SPECS["document"] == ("ems_document", "ems_doc_app", None)
    # vector installs pgvector
    assert mod.SLICE_SPECS["vector"] == ("ems_vector", "ems_vec_app", "vector")
    # timeseries installs pg_partman
    assert mod.SLICE_SPECS["timeseries"] == (
        "ems_timeseries",
        "ems_ts_app",
        "pg_partman",
    )


def test_measurements_schema_creates_partitioned_table_and_partman_parent() -> None:
    """Hardcoded SQL: CREATE TABLE PARTITION BY RANGE + partman.create_parent."""
    # Arrange + Act
    mod = _load_module()
    sql_block = "\n".join(mod.MEASUREMENTS_SCHEMA_SQL)

    # Assert
    assert "CREATE TABLE IF NOT EXISTS measurements" in sql_block
    assert "PARTITION BY RANGE (ts)" in sql_block
    assert "partman.create_parent" in sql_block
    assert "p_interval     => '1 hour'" in sql_block
    assert "retention = '7 days'" in sql_block
    # Q3 lock: JSONB value column, not DOUBLE PRECISION
    assert "value       JSONB" in sql_block


def test_put_secret_overwrites_cfn_placeholder_not_creates() -> None:
    """The slice secrets are CFN-native — Lambda overwrites via PutSecretValue.

    Calling create_secret would (a) fail (secret already exists), and (b)
    re-create the orphan-leak class the CFN-native shift eliminates. Make
    sure the helper takes the right path.
    """
    # Arrange — fake SM client tracking which method was called
    calls: list[tuple[str, dict]] = []

    class _FakeSM:
        def put_secret_value(self, **kw: object) -> None:
            calls.append(("put", kw))

        def create_secret(self, **kw: object) -> None:
            calls.append(("create", kw))

    mod = _load_module()

    # Act
    mod._put_secret(_FakeSM(), "arcnode-ems-stack/vector-url", "postgres://x")

    # Assert
    assert len(calls) == 1
    assert calls[0][0] == "put"
    assert calls[0][1] == {
        "SecretId": "arcnode-ems-stack/vector-url",
        "SecretString": "postgres://x",
    }
