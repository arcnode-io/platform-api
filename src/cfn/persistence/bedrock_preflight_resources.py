"""CFN resources for the Bedrock access preflight custom resource.

Three resources:

  * BedrockPreflightLambdaRole — least-priv role granting bedrock:InvokeModel
    on the two probe targets only (Titan embed + Sonnet 4.6 CRIS profile
    + the three foundation-model arns the CRIS spans).
  * BedrockPreflightLambda — python3.13 Lambda, source from
    `lambda_code/bedrock_preflight.py`. No VPC config — Bedrock is a
    public AWS API.
  * BedrockPreflightCustomResource — fires the Lambda at stack-create.
    Other resources should `DependsOn` this so the stack fails fast with
    a useful Reason before any billable infra spins up.

Cloud-only (commercial + defense). Airgapped customers ship without
Bedrock so this resource set is omitted from their template.
"""

from pathlib import Path
from typing import Final

from src.cfn.bedrock_models import (
    BEDROCK_CHAT_INFERENCE_PROFILE,
    BEDROCK_EMBED_FOUNDATION_MODEL,
    all_invoke_resources,
)

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"
DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


def _load_lambda_source(filename: str) -> str:
    """Read a Lambda source file as a string for embedding in CFN ZipFile."""
    return (LAMBDA_CODE_DIR / filename).read_text()


def bedrock_preflight_resources(
    *,
    lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
) -> dict[str, dict]:
    """Return the Lambda role + function + custom resource for Bedrock preflight.

    Returns CFN resource dicts; the outer dict maps logical-id -> resource body.
    """
    return {
        "BedrockPreflightLambdaRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                ],
                "Policies": [
                    {
                        "PolicyName": "bedrock-preflight-invoke",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    # Same resource list as the EC2 instance
                                    # role's bedrock policy — both pulled
                                    # from bedrock_models so they can't drift.
                                    "Effect": "Allow",
                                    "Action": "bedrock:InvokeModel",
                                    "Resource": all_invoke_resources(),
                                }
                            ],
                        },
                    },
                ],
            },
        },
        "BedrockPreflightLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": lambda_runtime,
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["BedrockPreflightLambdaRole", "Arn"]},
                "Timeout": 60,
                "Code": {"ZipFile": _load_lambda_source("bedrock_preflight.py")},
            },
        },
        "BedrockPreflightCustomResource": {
            "Type": "Custom::BedrockPreflight",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["BedrockPreflightLambda", "Arn"]},
                # Bump this string to force re-probe on stack update.
                "ProbeVersion": "v1",
                # Lambda reads model IDs from event.ResourceProperties so
                # the Lambda source stays generic; updates land here.
                "ChatModelId": BEDROCK_CHAT_INFERENCE_PROFILE,
                "EmbedModelId": BEDROCK_EMBED_FOUNDATION_MODEL,
            },
        },
    }
