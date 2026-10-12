"""Unit tests for the bundle URL segment: `<site-slug>-<order6>`."""

from uuid import UUID

import pytest

from src.bundle.bundle_path import parse_bundle_path, prefix_bounds


def test_parse_splits_the_order_prefix_off_the_slug() -> None:
    # Arrange
    segment = "brookside-dc-1-0123ab"

    # Act
    slug, prefix = parse_bundle_path(segment)

    # Assert
    assert slug == "brookside-dc-1"
    assert prefix == "0123ab"


def test_parse_rejects_a_segment_without_a_six_hex_prefix() -> None:
    # Arrange
    segment = "brookside-dc-1-zzzzzz"

    # Act / Assert
    with pytest.raises(ValueError):
        parse_bundle_path(segment)


def test_prefix_bounds_cover_every_order_id_with_that_prefix() -> None:
    # Arrange
    prefix = "0123ab"

    # Act
    low, high = prefix_bounds(prefix)

    # Assert
    assert low == UUID("0123ab00-0000-0000-0000-000000000000")
    assert high == UUID("0123abff-ffff-ffff-ffff-ffffffffffff")
