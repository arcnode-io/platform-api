"""Unit tests for commercial-variant vendor URL secrets + CFN params."""

from src.cfn.persistence.vendor_secrets import (
    agent_api_key_parameters,
    agent_api_key_secrets,
    commercial_url_parameters,
    vendor_url_secrets,
)


def test_vendor_url_secrets_returns_two_secrets() -> None:
    """Commercial vendor secrets: timeseries (Tiger) + graph (Aura)."""
    # Arrange + Act
    secrets = vendor_url_secrets()

    # Assert
    assert set(secrets.keys()) == {"TimeseriesUrlSecret", "GraphUrlSecret"}
    for s in secrets.values():
        assert s["Type"] == "AWS::SecretsManager::Secret"


def test_vendor_url_secrets_reference_cfn_params() -> None:
    """Secret values are `!Ref`s — customer-pasted URLs go through CFN, not the template body."""
    # Arrange + Act
    secrets = vendor_url_secrets()

    # Assert
    assert secrets["TimeseriesUrlSecret"]["Properties"]["SecretString"] == {
        "Ref": "TimeseriesConnectionUrl",
    }
    assert secrets["GraphUrlSecret"]["Properties"]["SecretString"] == {
        "Ref": "GraphConnectionUrl",
    }


def test_vendor_secret_names_follow_arcnode_ems_convention() -> None:
    """Secret names use ``arcnode-ems-{STACK}/<slot>-url`` so EC2 fetches uniformly."""
    # Arrange + Act
    secrets = vendor_url_secrets()

    # Assert
    assert (
        secrets["TimeseriesUrlSecret"]["Properties"]["Name"]["Fn::Sub"]
        == "arcnode-ems-${AWS::StackName}/timeseries-url"
    )
    assert (
        secrets["GraphUrlSecret"]["Properties"]["Name"]["Fn::Sub"]
        == "arcnode-ems-${AWS::StackName}/graph-url"
    )


def test_commercial_url_parameters_returns_two_required_params() -> None:
    """Two NoEcho String params, MinLength 1, no Default."""
    # Arrange + Act
    params = commercial_url_parameters()

    # Assert
    assert set(params.keys()) == {"TimeseriesConnectionUrl", "GraphConnectionUrl"}
    for p in params.values():
        assert p["Type"] == "String"
        assert p["NoEcho"] is True
        assert p["MinLength"] == 1
        assert "Default" not in p


def test_agent_api_key_secrets_returns_openweathermap_and_gridstatus() -> None:
    """Both third-party agent API keys get a Secrets Manager secret."""
    # Arrange + Act
    secrets = agent_api_key_secrets()

    # Assert
    assert set(secrets.keys()) == {
        "OpenweathermapApiKeySecret",
        "GridstatusApiKeySecret",
    }
    for s in secrets.values():
        assert s["Type"] == "AWS::SecretsManager::Secret"


def test_agent_api_key_secrets_reference_cfn_params() -> None:
    """Secret values are `!Ref`s to the matching NoEcho parameter."""
    # Arrange + Act
    secrets = agent_api_key_secrets()

    # Assert
    assert secrets["OpenweathermapApiKeySecret"]["Properties"]["SecretString"] == {
        "Ref": "OpenweathermapApiKey",
    }
    assert secrets["GridstatusApiKeySecret"]["Properties"]["SecretString"] == {
        "Ref": "GridstatusApiKey",
    }


def test_agent_api_key_parameters_returns_two_required_params() -> None:
    """Two NoEcho String params, MinLength 1, no Default."""
    # Arrange + Act
    params = agent_api_key_parameters()

    # Assert
    assert set(params.keys()) == {"OpenweathermapApiKey", "GridstatusApiKey"}
    for p in params.values():
        assert p["Type"] == "String"
        assert p["NoEcho"] is True
        assert p["MinLength"] == 1
        assert "Default" not in p
