"""Unit tests for orchestrator_service helpers."""

import pytest

from src.orchestrator.orchestrator_service import _slugify_site_id


class TestSlugifySiteId:
    """ASCII snake_case slug — operator names are user-supplied free-form text."""

    def test_simple_ascii_becomes_snake_case(self) -> None:
        assert _slugify_site_id("Nevada Facility 2") == "nevada_facility_2"

    def test_dashes_collapse_to_underscores(self) -> None:
        assert _slugify_site_id("Brookside DC-1") == "brookside_dc_1"

    def test_accented_chars_stripped(self) -> None:
        # 'é' is unicode-alnum but not ASCII; must be stripped.
        assert _slugify_site_id("Café 🔥 Site") == "caf_site"

    def test_pure_emoji_raises(self) -> None:
        # All-stripped input would write empty site_id to MQTT — refuse it.
        with pytest.raises(ValueError, match="slugifies to empty"):
            _slugify_site_id("🔥💯🎉")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="slugifies to empty"):
            _slugify_site_id("   ")

    def test_repeated_separators_collapse(self) -> None:
        assert _slugify_site_id("foo!!!bar...baz") == "foo_bar_baz"

    def test_strips_leading_trailing_underscores(self) -> None:
        assert _slugify_site_id("!!hello!!") == "hello"

    def test_kanji_stripped(self) -> None:
        assert _slugify_site_id("Tokyo 東京 site") == "tokyo_site"
