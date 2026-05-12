"""Tests for PersistenceService variant routing."""

from src.cfn.persistence.persistence_service import (
    PersistenceBuild,
    PersistenceService,
)
from src.orders.configurator_payload import DeploymentContext


def test_commercial_build_returns_aurora_plus_vendor_secrets() -> None:
    """Commercial variant: Aurora doc+vector + 2 CFN-native vendor URL secrets."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.COMMERCIAL)

    # Assert
    assert isinstance(build, PersistenceBuild)
    assert "AuroraCluster" in build.resources
    assert "TimeseriesUrlSecret" in build.resources
    assert "GraphUrlSecret" in build.resources
    # No defense-only resources
    assert "NeptuneCluster" not in build.resources
    assert "AossCollection" not in build.resources


def test_commercial_build_declares_two_required_parameters() -> None:
    """Commercial Parameters block: TimeseriesConnectionUrl + GraphConnectionUrl."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.COMMERCIAL)

    # Assert
    assert set(build.parameters.keys()) == {
        "TimeseriesConnectionUrl",
        "GraphConnectionUrl",
    }


def test_commercial_build_lists_ems_instance_dependencies() -> None:
    """EmsInstance waits for Aurora bootstrap + 2 vendor secrets."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.COMMERCIAL)

    # Assert
    assert set(build.ems_instance_depends_on) == {
        "AuroraBootstrapCustomResource",
        "TimeseriesUrlSecret",
        "GraphUrlSecret",
    }


def test_defense_build_returns_aurora_plus_neptune_plus_aoss() -> None:
    """Defense variant: Aurora doc+vector+timeseries + Neptune + AOSS, no vendor secrets."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert "AuroraCluster" in build.resources
    assert "NeptuneCluster" in build.resources
    assert "AossCollection" in build.resources
    # No commercial-only resources
    assert "TimeseriesUrlSecret" not in build.resources
    assert "GraphUrlSecret" not in build.resources


def test_defense_build_has_no_parameters() -> None:
    """Defense variant requires zero customer-supplied params."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert build.parameters == {}


def test_defense_build_lists_ems_instance_dependencies() -> None:
    """EmsInstance waits for Aurora bootstrap + Neptune + AOSS + 2 SSM params."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert set(build.ems_instance_depends_on) == {
        "AuroraBootstrapCustomResource",
        "NeptuneInstance",
        "AossCollection",
        "NeptuneHostParam",
        "AossHostParam",
    }


def test_sovereign_government_routes_to_defense_build() -> None:
    """SOVEREIGN_GOVERNMENT shares the defense variant — same resources."""
    # Arrange
    service = PersistenceService()

    # Act
    sovereign = service.build(
        deployment_context=DeploymentContext.SOVEREIGN_GOVERNMENT,
    )
    defense = service.build(deployment_context=DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert set(sovereign.resources.keys()) == set(defense.resources.keys())
    assert sovereign.parameters == defense.parameters
