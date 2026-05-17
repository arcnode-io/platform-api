"""Unit tests for the customer-URL preflight CFN resource set."""

from src.cfn.persistence.customer_url_preflight_resources import (
    customer_url_preflight_resources,
)


def test_returns_role_lambda_and_custom_resource() -> None:
    """Three logical-ids, matching the Bedrock preflight pattern."""
    # Arrange + Act
    resources = customer_url_preflight_resources()

    # Assert
    assert set(resources.keys()) == {
        "CustomerUrlPreflightLambdaRole",
        "CustomerUrlPreflightLambda",
        "CustomerUrlPreflightCustomResource",
    }


def test_lambda_runs_outside_vpc() -> None:
    """No VpcConfig — the Lambda dials public internet services (Tiger / Aura)."""
    # Arrange + Act
    fn = customer_url_preflight_resources()["CustomerUrlPreflightLambda"]

    # Assert
    assert "VpcConfig" not in fn["Properties"]


def test_lambda_runtime_overrideable() -> None:
    """LocalStack tests pass python3.12 because LocalStack lags new runtimes."""
    # Arrange + Act
    fn = customer_url_preflight_resources(lambda_runtime="python3.12")[
        "CustomerUrlPreflightLambda"
    ]

    # Assert
    assert fn["Properties"]["Runtime"] == "python3.12"


def test_lambda_role_only_grants_basic_execution() -> None:
    """No extra perms — handler only does outbound socket + ssl + urllib."""
    # Arrange + Act
    role = customer_url_preflight_resources()["CustomerUrlPreflightLambdaRole"]

    # Assert
    managed = role["Properties"]["ManagedPolicyArns"]
    assert len(managed) == 1
    assert "AWSLambdaBasicExecutionRole" in managed[0]["Fn::Sub"]
    assert "Policies" not in role["Properties"]


def test_custom_resource_threads_param_refs() -> None:
    """CR ResourceProperties pulls URLs from CFN params — Lambda reads from event."""
    # Arrange + Act
    cr = customer_url_preflight_resources()["CustomerUrlPreflightCustomResource"]

    # Assert
    props = cr["Properties"]
    assert props["TimeseriesUrl"] == {"Ref": "TimeseriesConnectionUrl"}
    assert props["GraphUrl"] == {"Ref": "GraphConnectionUrl"}
    assert cr["Type"] == "Custom::CustomerUrlPreflight"


def test_lambda_bundles_handler_source_inline() -> None:
    """Lambda Code.ZipFile is the python handler source — no S3 fetch."""
    # Arrange + Act
    fn = customer_url_preflight_resources()["CustomerUrlPreflightLambda"]

    # Assert
    src = fn["Properties"]["Code"]["ZipFile"]
    assert "def handler(" in src
    assert "_check_postgres" in src
    assert "_check_neo4j" in src
