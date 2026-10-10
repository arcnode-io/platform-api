"""Unit tests for the on-prem compose override."""

import yaml

from src.wizard.containers_compose import ONPREM_OVERRIDE


def test_override_puts_every_service_on_the_arcnode_network() -> None:
    # Arrange
    expected = {"default": {"name": "arcnode", "external": True}}

    # Act
    actual = yaml.safe_load(ONPREM_OVERRIDE)["networks"]

    # Assert
    assert actual == expected
