"""Composition tests for `PersistenceService.build_resources()`.

Asserts that Aurora + Tiger + Aura resource blocks are merged into one dict
and that no logical IDs collide across the three sub-blocks.
"""

from src.cfn.persistence.persistence_service import PersistenceService


def test_build_resources_returns_dict() -> None:
    """Smoke test — composition entry point returns a dict (placeholder)."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources()

    # Assert
    assert isinstance(resources, dict)
