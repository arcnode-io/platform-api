"""Unit tests for bedrock_preflight_resources() — CFN shape only.

Pure-function check: returns the right 3 resources, IAM policy lists
the same arns the EC2 instance role grants, and the custom resource
points at the Lambda.
"""

from src.cfn.persistence.bedrock_preflight_resources import (
    bedrock_preflight_resources,
)


def test_returns_three_resources_role_lambda_custom() -> None:
    # Arrange + Act
    resources = bedrock_preflight_resources()

    # Assert
    assert set(resources.keys()) == {
        "BedrockPreflightLambdaRole",
        "BedrockPreflightLambda",
        "BedrockPreflightCustomResource",
    }


def test_lambda_role_grants_invoke_on_titan_and_sonnet_cris() -> None:
    """Resources list must include the CRIS profile AND each underlying
    foundation-model arn across the 3 regions the profile spans."""
    # Arrange + Act
    resources = bedrock_preflight_resources()
    policy = resources["BedrockPreflightLambdaRole"]["Properties"]["Policies"][0]
    statement = policy["PolicyDocument"]["Statement"][0]

    # Assert
    assert statement["Action"] == "bedrock:InvokeModel"
    resource_strs = [
        r if isinstance(r, str) else r["Fn::Sub"] for r in statement["Resource"]
    ]
    joined = "\n".join(resource_strs)
    assert "us.anthropic.claude-sonnet-4-6" in joined  # CRIS profile
    assert "amazon.titan-embed-text-v2:0" in joined  # Titan FM
    for region in ("us-east-1", "us-east-2", "us-west-2"):
        assert (
            f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-sonnet-4-6"
            in joined
        )


def test_custom_resource_invokes_the_lambda() -> None:
    # Arrange + Act
    resources = bedrock_preflight_resources()
    cr = resources["BedrockPreflightCustomResource"]

    # Assert
    assert cr["Type"] == "Custom::BedrockPreflight"
    assert cr["Properties"]["ServiceToken"] == {
        "Fn::GetAtt": ["BedrockPreflightLambda", "Arn"]
    }


def test_lambda_inlines_the_source_file() -> None:
    """ZipFile must embed the actual bedrock_preflight.py text — no path stub."""
    # Arrange + Act
    resources = bedrock_preflight_resources()
    code_zip = resources["BedrockPreflightLambda"]["Properties"]["Code"]["ZipFile"]

    # Assert
    assert "def handler(" in code_zip
    assert "TITAN_MODEL" in code_zip
    assert "CLAUDE_PROFILE" in code_zip
