"""Unit tests for `aura_resources.aura_provisioning_resources`."""

from src.cfn.persistence.aura_resources import aura_provisioning_resources


def test_returns_lambda_role_lambda_and_custom_resource() -> None:
    resources = aura_provisioning_resources()
    assert "AuraLambdaRole" in resources
    assert "AuraLambda" in resources
    assert "AuraCustomResource" in resources


def test_lambda_uses_python_runtime() -> None:
    lambda_res = aura_provisioning_resources()["AuraLambda"]
    assert lambda_res["Properties"]["Runtime"] == "python3.13"


def test_custom_resource_passes_oauth_creds_through() -> None:
    cr = aura_provisioning_resources()["AuraCustomResource"]
    assert cr["Type"] == "Custom::Neo4jAuraInstance"
    props = cr["Properties"]
    assert props["Neo4jAuraClientId"] == {"Ref": "Neo4jAuraClientId"}
    assert props["Neo4jAuraClientSecret"] == {"Ref": "Neo4jAuraClientSecret"}
    assert props["Neo4jAuraTenantId"] == {"Ref": "Neo4jAuraTenantId"}
