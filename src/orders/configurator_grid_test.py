"""Unit tests for the grid-model types in configurator_grid.py."""

from src.orders.configurator_grid import SiteLocation


def test_an_off_grid_site_location_may_leave_lat_and_lon_null() -> None:
    """Off-grid orders have no utility point to resolve, so the coordinates can be null."""
    # Arrange
    raw = {"lat": None, "lon": None, "address": None}

    # Act
    location = SiteLocation.model_validate(raw)

    # Assert
    assert location.lat is None
    assert location.lon is None
