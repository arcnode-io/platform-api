"""Parsing for the bundle download URL: `/<site-slug>-<order6>/arcnode.zip`."""

import re
from typing import Final
from uuid import UUID

from src.bundle.bundle_record import ORDER_PREFIX_LENGTH

# Reason: the order prefix is the first hex digits of the order UUID, lowercase.
PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(.+)-([0-9a-f]{{{ORDER_PREFIX_LENGTH}}})$"
)
UUID_HEX_LENGTH: Final[int] = 32


def parse_bundle_path(segment: str) -> tuple[str, str]:
    """Split `<site-slug>-<order6>` into (slug, six-hex order prefix)."""
    match = PREFIX_PATTERN.match(segment)
    if match is None:
        raise ValueError(f"not a bundle path segment: {segment!r}")
    return match.group(1), match.group(2)


def prefix_bounds(prefix: str) -> tuple[UUID, UUID]:
    """Lowest and highest UUID that start with `prefix`, for a range query."""
    low = UUID(hex=prefix.ljust(UUID_HEX_LENGTH, "0"))
    high = UUID(hex=prefix.ljust(UUID_HEX_LENGTH, "f"))
    return low, high
