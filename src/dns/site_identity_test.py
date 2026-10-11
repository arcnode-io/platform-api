"""A cloud site's DNS name and its callback token.

The name is unique per order (two customers can pick the same site name) and valid as a
hostname (the site slug uses underscores). The token proves a callback comes from the
stack that order's template created, without storing anything."""

from src.dns.site_identity import (
    DOMAIN,
    site_host_label,
    site_hostname,
    site_token,
    token_matches,
)

ORDER_ID = "6f1c2a9e-0000-4000-8000-000000000042"


def test_the_hostname_is_the_site_slug_with_hyphens_plus_a_short_order_suffix() -> None:
    # Arrange + Act
    actual = site_hostname("nevada_facility_2", ORDER_ID)

    # Assert
    assert actual == f"nevada-facility-2-6f1c2a.{DOMAIN}"


def test_two_orders_for_the_same_site_name_get_different_hostnames() -> None:
    # Arrange + Act
    first = site_hostname("alpha", "6f1c2a9e-0000-4000-8000-000000000042")
    second = site_hostname("alpha", "a1b2c3d4-0000-4000-8000-000000000099")

    # Assert
    assert first != second


def test_a_long_site_slug_is_cut_so_the_label_stays_a_valid_dns_label() -> None:
    # Arrange
    slug = "x" * 120

    # Act
    label = site_host_label(slug, ORDER_ID)

    # Assert — DNS labels are at most 63 characters
    assert len(label) <= 63
    assert label.endswith("-6f1c2a")


def test_the_token_matches_only_its_own_order_and_secret() -> None:
    # Arrange
    token = site_token("s3cret", ORDER_ID)

    # Act + Assert
    assert token_matches("s3cret", ORDER_ID, token)
    assert not token_matches("s3cret", "a1b2c3d4-0000-4000-8000-000000000099", token)
    assert not token_matches("other-secret", ORDER_ID, token)
    assert not token_matches("s3cret", ORDER_ID, "")
