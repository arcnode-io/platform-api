"""Unit tests for `tiger_resources.tiger_provisioning_resources`."""

from src.cfn.persistence.tiger_resources import tiger_provisioning_resources


def test_returns_lambda_role_lambda_and_custom_resource() -> None:
    resources = tiger_provisioning_resources()
    assert "TigerLambdaRole" in resources
    assert "TigerLambda" in resources
    assert "TigerCustomResource" in resources


def test_lambda_uses_python_runtime() -> None:
    lambda_res = tiger_provisioning_resources()["TigerLambda"]
    assert lambda_res["Type"] == "AWS::Lambda::Function"
    assert lambda_res["Properties"]["Runtime"] == "python3.13"


def test_custom_resource_passes_vendor_token_params_through() -> None:
    cr = tiger_provisioning_resources()["TigerCustomResource"]
    assert cr["Type"] == "Custom::TigerCloudInstance"
    props = cr["Properties"]
    assert props["TigerCloudAccessKey"] == {"Ref": "TigerCloudAccessKey"}
    assert props["TigerCloudSecretKey"] == {"Ref": "TigerCloudSecretKey"}
    assert props["TigerCloudProjectId"] == {"Ref": "TigerCloudProjectId"}
    assert "DeploymentUuid" in props
