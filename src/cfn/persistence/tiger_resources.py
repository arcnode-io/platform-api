"""Tiger Cloud CFN resources — Lambda + IAM role + custom resource trigger."""

from pathlib import Path
from typing import Final

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"


def _load_lambda_source(filename: str) -> str:
    return (LAMBDA_CODE_DIR / filename).read_text()


def tiger_provisioning_resources() -> dict[str, dict]:
    """CFN resources that provision a Tiger Cloud service via REST API."""
    return {
        "TigerLambdaRole": {
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
                        "PolicyName": "tiger-secret-write",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "secretsmanager:CreateSecret",
                                        "secretsmanager:DeleteSecret",
                                        "secretsmanager:PutSecretValue",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "TigerLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": "python3.13",
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["TigerLambdaRole", "Arn"]},
                "Timeout": 900,
                "Code": {"ZipFile": _load_lambda_source("tiger_provisioner.py")},
            },
        },
        "TigerCustomResource": {
            "Type": "Custom::TigerCloudInstance",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["TigerLambda", "Arn"]},
                "TigerCloudAccessKey": {"Ref": "TigerCloudAccessKey"},
                "TigerCloudSecretKey": {"Ref": "TigerCloudSecretKey"},
                "TigerCloudProjectId": {"Ref": "TigerCloudProjectId"},
                "DeploymentUuid": {"Ref": "AWS::StackName"},
            },
        },
    }
