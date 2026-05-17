"""CFN resources for the customer-URL preflight custom resource.

Commercial-only: validates the operator-supplied Tiger Cloud + Neo4j Aura
URLs at stack-create time before any billable infra (Aurora cluster ~10min)
spins up. Catches DNS typos, wrong ports, missing IP allow-list entries,
paused vendor services, TLS cert issues, and wrong-protocol-on-port.

Does NOT validate auth — the Lambda is zero-dep (socket + ssl + urllib
in the python3.13 runtime, no psycopg2 / neo4j layer). Bad passwords
still fail at compose-start, but everything else fails fast within ~10s.

Three resources mirror the Bedrock preflight pattern:
  * CustomerUrlPreflightLambdaRole — basic-execution only (no extra perms;
    the Lambda only does outbound TCP/TLS).
  * CustomerUrlPreflightLambda — python3.13 outside VPC (the URLs target
    public internet services).
  * CustomerUrlPreflightCustomResource — fires the Lambda at stack-create.
"""

from pathlib import Path
from typing import Final

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"
DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


def _load_lambda_source(filename: str) -> str:
    """Read a Lambda source file as a string for embedding in CFN ZipFile."""
    return (LAMBDA_CODE_DIR / filename).read_text()


def customer_url_preflight_resources(
    *,
    lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
) -> dict[str, dict]:
    """Return the Lambda role + function + custom resource for URL preflight.

    Returns CFN resource dicts; the outer dict maps logical-id -> resource body.
    """
    return {
        "CustomerUrlPreflightLambdaRole": {
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
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                    },
                ],
            },
        },
        "CustomerUrlPreflightLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": lambda_runtime,
                "Handler": "index.handler",
                "Role": {
                    "Fn::GetAtt": ["CustomerUrlPreflightLambdaRole", "Arn"],
                },
                "Timeout": 30,
                "Code": {"ZipFile": _load_lambda_source("customer_url_preflight.py")},
            },
        },
        "CustomerUrlPreflightCustomResource": {
            "Type": "Custom::CustomerUrlPreflight",
            "Properties": {
                "ServiceToken": {
                    "Fn::GetAtt": ["CustomerUrlPreflightLambda", "Arn"],
                },
                "TimeseriesUrl": {"Ref": "TimeseriesConnectionUrl"},
                "GraphUrl": {"Ref": "GraphConnectionUrl"},
            },
        },
    }
