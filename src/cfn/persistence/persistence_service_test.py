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
    build = service.build(
        deployment_context=DeploymentContext.COMMERCIAL, short="abcd1234"
    )

    # Assert
    assert isinstance(build, PersistenceBuild)
    assert "AuroraCluster" in build.resources
    assert "TimeseriesUrlSecret" in build.resources
    assert "GraphUrlSecret" in build.resources
    # No defense-only resources
    assert "NeptuneCluster" not in build.resources
    assert "AossCollection" not in build.resources


def test_commercial_build_declares_required_parameters() -> None:
    """Commercial Parameters: vendor URLs + agent vendor API keys."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.COMMERCIAL, short="abcd1234"
    )

    # Assert
    assert set(build.parameters.keys()) == {
        "TimeseriesConnectionUrl",
        "GraphConnectionUrl",
        "OpenweathermapApiKey",
    }


def test_commercial_build_lists_ems_instance_dependencies() -> None:
    """EmsInstance waits for Aurora bootstrap + vendor secrets + agent keys."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.COMMERCIAL, short="abcd1234"
    )

    # Assert
    assert set(build.ems_instance_depends_on) == {
        "AuroraBootstrapCustomResource",
        "TimeseriesUrlSecret",
        "GraphUrlSecret",
        "OpenweathermapApiKeySecret",
        "CustomerUrlPreflightCustomResource",
    }


def test_defense_build_returns_aurora_plus_neptune_plus_aoss() -> None:
    """Defense variant: Aurora doc+vector+timeseries + Neptune + AOSS, no vendor secrets."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.DEFENSE_FORWARD, short="abcd1234"
    )

    # Assert
    assert "AuroraCluster" in build.resources
    assert "NeptuneCluster" in build.resources
    assert "AossCollection" in build.resources
    # No commercial-only resources
    assert "TimeseriesUrlSecret" not in build.resources
    assert "GraphUrlSecret" not in build.resources


def test_defense_build_declares_agent_api_key_parameters() -> None:
    """Defense Parameters: only OpenWeatherMap remains.

    Per ADR-024 chat + embed go through Bedrock; the only third-party
    API key the agent still needs is OpenWeatherMap (per ADR-025).
    All other persistence URLs are CFN-internal.
    """
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.DEFENSE_FORWARD, short="abcd1234"
    )

    # Assert
    assert set(build.parameters.keys()) == {"OpenweathermapApiKey"}


def test_defense_build_lists_ems_instance_dependencies() -> None:
    """EmsInstance waits for Aurora bootstrap + Neptune + AOSS + 3 SSM params."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.DEFENSE_FORWARD, short="abcd1234"
    )

    # Assert
    assert set(build.ems_instance_depends_on) == {
        "AuroraBootstrapCustomResource",
        "OpenweathermapApiKeySecret",
        "NeptuneInstance",
        "AossCollection",
        "NeptuneHostParam",
        "NeptuneLoaderRoleArnParam",
        "AossHostParam",
    }


def test_sovereign_government_routes_to_defense_build() -> None:
    """SOVEREIGN_GOVERNMENT shares the defense variant — same resources."""
    # Arrange
    service = PersistenceService()

    # Act
    sovereign = service.build(
        deployment_context=DeploymentContext.SOVEREIGN_GOVERNMENT,
        short="abcd1234",
    )
    defense = service.build(
        deployment_context=DeploymentContext.DEFENSE_FORWARD, short="abcd1234"
    )

    # Assert
    assert set(sovereign.resources.keys()) == set(defense.resources.keys())
    assert sovereign.parameters == defense.parameters
