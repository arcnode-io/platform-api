"""Tests for the EMQX rule HOCON renderer.

The script lives under `init-scripts/` (hyphenated, matching the S3 path
it's published to) — not a Python-importable name. Load it via importlib
the same way `lambda_code/` does.
"""

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent / "render_emqx_rule.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("render_emqx_rule", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEMPLATE = """\
connectors.postgresql.timeseries {{
  server = "{host}:{port}"
  database = "{db}"
  username = "{user}"
  password = "{password}"
}}
"""


def test_renders_postgres_url_into_separate_fields() -> None:
    """Standard postgres://user:pass@host:port/db parses into the 5 HOCON fields."""
    # Arrange
    mod = _load_module()

    # Act
    out = mod.render(
        TEMPLATE, timeseries_url="postgres://app:s3cr3t@db.example:5432/ems_timeseries"
    )

    # Assert
    assert 'server = "db.example:5432"' in out
    assert 'database = "ems_timeseries"' in out
    assert 'username = "app"' in out
    assert 'password = "s3cr3t"' in out


def test_renders_postgresql_scheme_too() -> None:
    """`postgresql://` is the longer alias of `postgres://`; both must parse."""
    # Arrange
    mod = _load_module()

    # Act
    out = mod.render(TEMPLATE, timeseries_url="postgresql://u:p@h:5432/d")

    # Assert
    assert 'server = "h:5432"' in out


def test_strips_query_string_from_db_name() -> None:
    """Tiger Cloud URLs carry `?sslmode=require`; db name is the path only."""
    # Arrange
    mod = _load_module()

    # Act
    out = mod.render(
        TEMPLATE,
        timeseries_url="postgres://u:p@tiger.example/ems_timeseries?sslmode=require",
    )

    # Assert
    assert 'database = "ems_timeseries"' in out


def test_defaults_port_to_5432_when_missing() -> None:
    """URL without explicit port falls back to Postgres's default 5432."""
    # Arrange
    mod = _load_module()

    # Act
    out = mod.render(TEMPLATE, timeseries_url="postgres://u:p@h/d")

    # Assert
    assert 'server = "h:5432"' in out


def test_rejects_non_postgres_scheme() -> None:
    """Anything that's not postgres / postgresql is a programming error — fail fast."""
    # Arrange
    mod = _load_module()

    # Act + Assert
    with pytest.raises(ValueError, match="unexpected scheme"):
        mod.render(TEMPLATE, timeseries_url="mysql://u:p@h/d")


def test_rejects_missing_credentials() -> None:
    """A URL without password is a bootstrap-time misconfiguration."""
    # Arrange
    mod = _load_module()

    # Act + Assert
    with pytest.raises(ValueError, match="host, username, and password"):
        mod.render(TEMPLATE, timeseries_url="postgres://h:5432/d")


def test_rejects_missing_database_name() -> None:
    """Postgres URL with no path has no DB to write to — bail."""
    # Arrange
    mod = _load_module()

    # Act + Assert
    with pytest.raises(ValueError, match="database name"):
        mod.render(TEMPLATE, timeseries_url="postgres://u:p@h:5432/")


@pytest.mark.parametrize(
    "variant_dir",
    ["commercial-and-iso", "defense"],
)
def test_real_hocon_templates_render_cleanly(variant_dir: str) -> None:
    """Both shipped HOCON templates render without unsubstituted braces.

    Catches escaping bugs: format-string `{...}` in our template that
    isn't a substitution placeholder must be doubled `{{...}}`.
    """
    # Arrange
    mod = _load_module()
    template_path = Path(__file__).parents[1] / "emqx" / variant_dir / "rule.hocon"
    template = template_path.read_text()

    # Act
    rendered = mod.render(
        template,
        timeseries_url="postgres://app:pw@db.example:5432/ems_timeseries",
    )

    # Assert — substitutions landed
    assert "db.example" in rendered
    assert "ems_timeseries" in rendered
    # Assert — HOCON syntax preserved (curly braces present, intact)
    assert "connectors.postgresql.timeseries {" in rendered
    assert "rule_engine.rules.telemetry_write {" in rendered
    # Assert — EMQX rule-engine `${var}` references intact
    assert "${ts}::timestamptz" in rendered
    assert "${value}::jsonb" in rendered
    # Assert — no stray format-string placeholders left in CODE lines
    # (the template's docstring intentionally lists {host}, {password},
    # etc. as literal text — doubled braces escape Python's str.format
    # so they don't accidentally render into a comment).
    body_lines = [ln for ln in rendered.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(body_lines)
    assert "{host}" not in body
    assert "{password}" not in body
