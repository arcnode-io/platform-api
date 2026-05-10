"""Composition tests for `PersistenceService.build_resources()`.

Asserts that Aurora + Tiger + Aura resource blocks are merged into one dict
and that no logical IDs collide across the three sub-blocks.
"""

from src.cfn.persistence.aura_resources import aura_provisioning_resources
from src.cfn.persistence.aurora_resources import aurora_cluster_resources
from src.cfn.persistence.persistence_service import PersistenceService
from src.cfn.persistence.tiger_resources import tiger_provisioning_resources


def test_build_resources_returns_dict() -> None:
    """Smoke test — composition entry point returns a dict."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources()

    # Assert
    assert isinstance(resources, dict)


def test_build_resources_merges_aurora_tiger_and_aura() -> None:
    """All three sub-blocks present in the merged dict."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources()

    # Assert — pick one representative key from each block
    assert "AuroraCluster" in resources  # Aurora
    assert "TigerCustomResource" in resources  # Tiger
    assert "AuraCustomResource" in resources  # Aura


def test_build_resources_keys_are_unique() -> None:
    """No accidental key collision across the three sub-blocks."""
    # Arrange + Act
    aurora_keys = set(aurora_cluster_resources().keys())
    tiger_keys = set(tiger_provisioning_resources().keys())
    aura_keys = set(aura_provisioning_resources().keys())

    # Assert — no overlap
    assert aurora_keys.isdisjoint(tiger_keys)
    assert aurora_keys.isdisjoint(aura_keys)
    assert tiger_keys.isdisjoint(aura_keys)
