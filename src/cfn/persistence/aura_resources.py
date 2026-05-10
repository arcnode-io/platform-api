"""Neo4j Aura CFN resources — Lambda + IAM role + custom resource trigger."""

from pathlib import Path
from typing import Final

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"


def _load_lambda_source(filename: str) -> str:
    return (LAMBDA_CODE_DIR / filename).read_text()


def aura_provisioning_resources() -> dict[str, object]:
    """CFN resources that provision a Neo4j Aura instance via REST API."""
    return {
        "AuraLambdaRole": {
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
                        "PolicyName": "aura-secret-write",
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
        "AuraLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": "python3.13",
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["AuraLambdaRole", "Arn"]},
                "Timeout": 900,
                "Code": {"ZipFile": _load_lambda_source("aura_provisioner.py")},
            },
        },
        "AuraCustomResource": {
            "Type": "Custom::Neo4jAuraInstance",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["AuraLambda", "Arn"]},
                "Neo4jAuraClientId": {"Ref": "Neo4jAuraClientId"},
                "Neo4jAuraClientSecret": {"Ref": "Neo4jAuraClientSecret"},
                "Neo4jAuraTenantId": {"Ref": "Neo4jAuraTenantId"},
                "DeploymentUuid": {"Ref": "AWS::StackName"},
            },
        },
    }
