"""Composition tests for `PersistenceService.build_resources()`.

Asserts that Aurora resources are present per variant. Neptune+AOSS (defense)
and vendor-URL secrets (commercial) land in follow-up commits — those
asserts will join here then.
"""

from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext


def test_commercial_build_resources_returns_dict() -> None:
    """Smoke test — commercial composition returns a dict."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources(deployment_context=DeploymentContext.COMMERCIAL)

    # Assert
    assert isinstance(resources, dict)
    assert "AuroraCluster" in resources


def test_defense_build_resources_returns_dict() -> None:
    """Smoke test — defense composition returns a dict."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources(
        deployment_context=DeploymentContext.DEFENSE_FORWARD
    )

    # Assert
    assert isinstance(resources, dict)
    assert "AuroraCluster" in resources
