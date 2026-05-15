"""Neptune Serverless CFN resources — defense variant only.

Cluster + instance + a serverless scaling config + a loader IAM role for
S3 reads at bulk-import time. Endpoint hostname lands in SSM Parameter
Store under ``/arcnode-ems/{STACK}/neptune-host`` so EC2 UserData can
resolve it without holding a credential — Neptune auth is IAM-signed via
the instance profile. Loader role ARN lands in SSM at
``/arcnode-ems/{STACK}/neptune-loader-role-arn`` so the
seed-graph-neptune init container can pass it to ``StartLoaderJob``.

Demo defaults target the cheapest possible footprint:
  - 1 NCU floor (Serverless minimum; can't go lower)
  - Two AZs (EmsSubnet + EmsSubnetB) — Neptune enforces multi-AZ subnet group
"""

from typing import Final

MIN_NCU: Final[float] = 1.0  # Neptune Serverless floor
MAX_NCU_DEFAULT: Final[float] = 128.0  # AWS hard cap; rarely hit in demo

NEPTUNE_HOST_SSM_PARAM: Final[str] = "/arcnode-ems/${AWS::StackName}/neptune-host"
NEPTUNE_LOADER_ROLE_SSM_PARAM: Final[str] = (
    "/arcnode-ems/${AWS::StackName}/neptune-loader-role-arn"
)
ARCNODE_PUBLIC_SEED_PREFIX: Final[str] = (
    "arn:aws:s3:::arcnode-public/seed/graph-neptune/*"
)


def neptune_resources(
    min_ncu: float = MIN_NCU,
    max_ncu: float = MAX_NCU_DEFAULT,
) -> dict[str, dict]:
    """CFN resources for a Neptune Serverless graph database.

    Endpoint hostname is published to SSM Parameter Store so EC2 UserData
    can fetch it without holding any secret — IAM-auth handles credentials.
    """
    return {
        "NeptuneSubnetGroup": {
            "Type": "AWS::Neptune::DBSubnetGroup",
            "Properties": {
                "DBSubnetGroupDescription": "Neptune serverless subnet group",
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnetB"}],
            },
        },
        "NeptuneSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Neptune serverless ingress (Gremlin/openCypher)",
                "VpcId": {"Ref": "EmsVpc"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 8182,
                        "ToPort": 8182,
                        "SourceSecurityGroupId": {"Ref": "EmsSecurityGroup"},
                    }
                ],
            },
        },
        "NeptuneLoaderRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "rds.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "neptune-loader-read-arcnode-public",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject", "s3:ListBucket"],
                                    "Resource": [
                                        "arn:aws:s3:::arcnode-public",
                                        ARCNODE_PUBLIC_SEED_PREFIX,
                                    ],
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "NeptuneCluster": {
            "Type": "AWS::Neptune::DBCluster",
            "Properties": {
                "DBSubnetGroupName": {"Ref": "NeptuneSubnetGroup"},
                "VpcSecurityGroupIds": [{"Ref": "NeptuneSecurityGroup"}],
                "ServerlessScalingConfiguration": {
                    "MinCapacity": min_ncu,
                    "MaxCapacity": max_ncu,
                },
                # IAM auth — EC2 instance profile carries the policy that
                # grants neptune-db:* against this cluster's ARN. No password.
                "IamAuthEnabled": True,
                # Neptune assumes this role to read bulk-loader CSV from
                # arcnode-public S3 at seed time.
                "AssociatedRoles": [
                    {"RoleArn": {"Fn::GetAtt": ["NeptuneLoaderRole", "Arn"]}}
                ],
            },
        },
        "NeptuneInstance": {
            "Type": "AWS::Neptune::DBInstance",
            "Properties": {
                "DBClusterIdentifier": {"Ref": "NeptuneCluster"},
                "DBInstanceClass": "db.serverless",
            },
        },
        "NeptuneHostParam": {
            "Type": "AWS::SSM::Parameter",
            "Properties": {
                "Name": {
                    "Fn::Sub": "/arcnode-ems/${AWS::StackName}/neptune-host",
                },
                "Type": "String",
                "Value": {"Fn::GetAtt": ["NeptuneCluster", "Endpoint"]},
                "Description": "Neptune cluster endpoint hostname (IAM-auth)",
            },
        },
        "NeptuneLoaderRoleArnParam": {
            "Type": "AWS::SSM::Parameter",
            "Properties": {
                "Name": {
                    "Fn::Sub": (
                        "/arcnode-ems/${AWS::StackName}/neptune-loader-role-arn"
                    ),
                },
                "Type": "String",
                "Value": {"Fn::GetAtt": ["NeptuneLoaderRole", "Arn"]},
                "Description": (
                    "ARN of the IAM role Neptune assumes to read seed CSV "
                    "from arcnode-public during bulk load."
                ),
            },
        },
    }
