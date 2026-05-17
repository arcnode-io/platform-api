"""Aurora serverless PG CFN resources — cluster, instance, master secret.

Engine version 16.4 (PG 16.x supports scale-to-0 ACU; 16.3+ required).
The cluster sits in the existing public subnet for MVP; locking it into
private subnets is a future hardening step (introduces NAT, changes
cost; out of scope here).
"""

from pathlib import Path
from typing import Final

ENGINE_VERSION: Final[str] = "16.4"
SECONDS_UNTIL_AUTO_PAUSE: Final[int] = 300  # 5 min idle → auto-pause
MASTER_USERNAME: Final[str] = "ems_master"
LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"
# Public psycopg2 layer for python3.13. Replace with self-published layer
# once a stable arcnode-hosted layer is available; arn shown is a known
# community publisher — region must be substituted at template-render time.
PSYCOPG2_LAYER_ARN_TEMPLATE: Final[str] = (
    "arn:${AWS::Partition}:lambda:${AWS::Region}:878287304298:layer:psycopg2-py313:1"
)
DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


def _load_lambda_source(filename: str) -> str:
    """Read a Lambda source file as a string for embedding in CFN ZipFile."""
    return (LAMBDA_CODE_DIR / filename).read_text()


# Per-variant Aurora slice sets. Commercial keeps only document + vector
# (Tiger Cloud owns the timeseries slice). Defense adds timeseries (Aurora
# pg_partman absorbs telemetry).
COMMERCIAL_SLICES: Final[tuple[str, ...]] = ("document", "vector")
DEFENSE_SLICES: Final[tuple[str, ...]] = ("document", "vector", "timeseries")


def aurora_cluster_resources(
    lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
    psycopg2_layer_arn_template: str | None = PSYCOPG2_LAYER_ARN_TEMPLATE,
    slices: tuple[str, ...] = COMMERCIAL_SLICES,
) -> dict[str, dict]:
    """CFN resources for a scale-to-0 Aurora serverless PG cluster.

    `slices` lists the per-variant database names the bootstrap Lambda must
    create. The custom resource receives the list as a CFN property; the
    Lambda branches on it. Defaults to commercial (`document + vector`).

    `psycopg2_layer_arn_template=None` omits the Layers field — the test
    deploy uses this because LocalStack community can't fetch shared layers
    from real AWS (Pro-only feature). Prod always sets the layer.
    """
    return {
        "AuroraMasterSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Description": "Aurora master credentials (managed rotation)",
                "GenerateSecretString": {
                    "SecretStringTemplate": f'{{"username": "{MASTER_USERNAME}"}}',
                    "GenerateStringKey": "password",
                    "PasswordLength": 32,
                    "ExcludeCharacters": '"@/\\',
                },
            },
        },
        "AuroraSubnetGroup": {
            "Type": "AWS::RDS::DBSubnetGroup",
            "Properties": {
                "DBSubnetGroupDescription": "Aurora serverless subnet group",
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnetB"}],
            },
        },
        "AuroraSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Aurora serverless ingress (Postgres)",
                "VpcId": {"Ref": "EmsVpc"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 5432,
                        "ToPort": 5432,
                        "SourceSecurityGroupId": {"Ref": "EmsSecurityGroup"},
                    }
                ],
            },
        },
        "AuroraCluster": {
            "Type": "AWS::RDS::DBCluster",
            "Properties": {
                "Engine": "aurora-postgresql",
                "EngineMode": "provisioned",
                "EngineVersion": ENGINE_VERSION,
                "MasterUsername": MASTER_USERNAME,
                "MasterUserPassword": {
                    "Fn::Sub": "{{resolve:secretsmanager:${AuroraMasterSecret}::password}}"
                },
                "DBSubnetGroupName": {"Ref": "AuroraSubnetGroup"},
                "VpcSecurityGroupIds": [{"Ref": "AuroraSecurityGroup"}],
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 0,
                    "MaxCapacity": 4,
                    "SecondsUntilAutoPause": SECONDS_UNTIL_AUTO_PAUSE,
                },
            },
        },
        "AuroraInstance": {
            "Type": "AWS::RDS::DBInstance",
            "Properties": {
                "DBClusterIdentifier": {"Ref": "AuroraCluster"},
                "DBInstanceClass": "db.serverless",
                "Engine": "aurora-postgresql",
                "EngineVersion": ENGINE_VERSION,
            },
        },
        "AuroraBootstrapLambdaRole": {
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
                        "Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
                    },
                ],
                "Policies": [
                    {
                        "PolicyName": "aurora-bootstrap-secrets",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "secretsmanager:GetSecretValue",
                                        "secretsmanager:CreateSecret",
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
        "AuroraBootstrapLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": lambda_runtime,
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["AuroraBootstrapLambdaRole", "Arn"]},
                "Timeout": 300,
                "Code": {"ZipFile": _load_lambda_source("aurora_bootstrap.py")},
                "VpcConfig": {
                    "SubnetIds": [{"Ref": "EmsSubnet"}],
                    "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
                },
                **(
                    {"Layers": [{"Fn::Sub": psycopg2_layer_arn_template}]}
                    if psycopg2_layer_arn_template is not None
                    else {}
                ),
            },
        },
        "AuroraBootstrapCustomResource": {
            "Type": "Custom::AuroraBootstrap",
            # DeletionPolicy + UpdateReplacePolicy = Retain: CFN does NOT
            # invoke the Lambda on stack delete. The Aurora cluster is being
            # deleted anyway, so the per-slice DBs + app users go with it —
            # the Delete handler is a no-op in our code. Skipping it dodges
            # an upstream Lambda-in-VPC bug where the Hyperplane ENI loses
            # its route to the S3 CFN ResponseURL after sitting idle ~20min
            # post-create, causing the Lambda to time out and CFN to hang
            # ~1hr before declaring DELETE_FAILED. Verified live 2026-05-17:
            # CREATE works in 4s, DELETE timed out at 246s on same ENI.
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "DependsOn": "AuroraInstance",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["AuroraBootstrapLambda", "Arn"]},
                "ClusterEndpoint": {
                    "Fn::GetAtt": ["AuroraCluster", "Endpoint.Address"]
                },
                "MasterSecretArn": {"Ref": "AuroraMasterSecret"},
                "DeploymentUuid": {"Ref": "AWS::StackName"},
                # Per-variant slice list — Lambda creates one db per slice and
                # writes its connection string to arcnode-ems-{STACK}/<slice>-url.
                "Slices": list(slices),
            },
        },
    }
