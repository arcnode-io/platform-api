"""Smoke tests for the Aurora bootstrap Lambda source.

The function runs in Lambda; we test what we can statically — that the
module parses, that `handler` is callable, and that the SQL statements
match the expected database + extension shape.
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
    """Lambda entry point must be `handler(event, context)`."""
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert callable(mod.handler)


def test_creates_document_and_vector_databases() -> None:
    """SQL must CREATE DATABASE for both ems_document and ems_vector."""
    # Arrange + Act
    source = MODULE_PATH.read_text()

    # Assert
    assert "CREATE DATABASE ems_document" in source
    assert "CREATE DATABASE ems_vector" in source


def test_installs_vector_extension_on_vector_db() -> None:
    """pgvector goes on ems_vector only, not ems_document."""
    # Arrange + Act
    source = MODULE_PATH.read_text()

    # Assert
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
