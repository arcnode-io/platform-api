"""Neptune Serverless CFN resources — defense variant only.

Cluster + instance + a serverless scaling config. Endpoint hostname lands
in SSM Parameter Store under ``/arcnode-ems/{STACK}/neptune-host`` so the
EC2 instance can resolve it without holding a credential — Neptune auth
is IAM-signed via the instance profile.

Demo defaults target the cheapest possible footprint:
  - 1 NCU floor (Serverless minimum; can't go lower)
  - Single AZ — Aurora-style subnet group "two entries same subnet" trick
"""

from typing import Final

MIN_NCU: Final[float] = 1.0  # Neptune Serverless floor
MAX_NCU_DEFAULT: Final[float] = 128.0  # AWS hard cap; rarely hit in demo

NEPTUNE_HOST_SSM_PARAM: Final[str] = "/arcnode-ems/${AWS::StackName}/neptune-host"


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
                # Same single-AZ trick as Aurora's subnet group — Neptune
                # also requires 2 entries; we duplicate the public subnet
                # until network_resources() adds a second AZ.
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnet"}],
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
    }
