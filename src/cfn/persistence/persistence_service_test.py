"""Tests for PersistenceService variant routing."""

import pytest

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
        "GridstatusApiKey",
        "MqttServicePw",
        "AuthJwtSecret",
        "AuthOperatorPw",
        "AuthViewerPw",
        "GrafanaAdminPw",
        "DbPassword",
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
        "GridstatusApiKeySecret",
        "CustomerUrlPreflightCustomResource",
        "MqttServicePwSecret",
        "DerControlTruststoreSecret",
        "DerControlLfdiAllowlistSecret",
        "AuthJwtSecretSecret",
        "AuthOperatorPwSecret",
        "AuthViewerPwSecret",
        "GrafanaAdminPwSecret",
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
    """Defense Parameters: the two third-party agent API keys.

    Per ADR-024 chat + embed go through Bedrock; OpenWeatherMap (weather
    tool) and GridStatus (ISO market-data tool, per ADR-025) are the only
    third-party keys the agent still needs. All other persistence URLs
    are CFN-internal.
    """
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(
        deployment_context=DeploymentContext.DEFENSE_FORWARD, short="abcd1234"
    )

    # Assert — agent keys + the customer-set passwords
    assert set(build.parameters.keys()) == {
        "OpenweathermapApiKey",
        "GridstatusApiKey",
        "MqttServicePw",
        "AuthJwtSecret",
        "AuthOperatorPw",
        "AuthViewerPw",
        "GrafanaAdminPw",
        "DbPassword",
    }


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
        "GridstatusApiKeySecret",
        "NeptuneInstance",
        "AossCollection",
        "NeptuneHostParam",
        "NeptuneLoaderRoleArnParam",
        "AossHostParam",
        "MqttServicePwSecret",
        "DerControlTruststoreSecret",
        "DerControlLfdiAllowlistSecret",
        "AuthJwtSecretSecret",
        "AuthOperatorPwSecret",
        "AuthViewerPwSecret",
        "GrafanaAdminPwSecret",
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


@pytest.mark.parametrize(
    "context", [DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD]
)
def test_the_template_makes_up_no_password(context: DeploymentContext) -> None:
    """The customer sets every password, same as on-prem: no secret is a CFN-random value."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=context, short="abcd1234")

    # Assert
    generated = [
        name
        for name, resource in build.resources.items()
        if "GenerateSecretString" in resource.get("Properties", {})
    ]
    assert generated == []


@pytest.mark.parametrize(
    "context", [DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD]
)
def test_the_customer_sets_the_broker_token_and_database_passwords(
    context: DeploymentContext,
) -> None:
    """Mirrors the on-prem wizard: one broker service password, the session-token
    key, and one database password, each a NoEcho parameter."""
    # Arrange
    service = PersistenceService()

    # Act
    build = service.build(deployment_context=context, short="abcd1234")

    # Assert
    for name in ("MqttServicePw", "AuthJwtSecret", "DbPassword"):
        assert build.parameters[name]["NoEcho"] is True, name
    assert build.parameters["AuthJwtSecret"]["MinLength"] == 32
