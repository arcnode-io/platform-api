"""Aurora serverless PG CFN resources — cluster, instance, master secret.

Engine version 16.4 (PG 16.x supports scale-to-0 ACU; 16.3+ required).
The cluster sits in the existing public subnet for MVP; locking it into
private subnets is a future hardening step (introduces NAT, changes
cost; out of scope here).
"""

from typing import Final

ENGINE_VERSION: Final[str] = "16.4"
SECONDS_UNTIL_AUTO_PAUSE: Final[int] = 300  # 5 min idle → auto-pause
MASTER_USERNAME: Final[str] = "ems_master"


def aurora_cluster_resources() -> dict[str, object]:
    """CFN resources for a scale-to-0 Aurora serverless PG cluster."""
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
                # MVP: reuse the existing public subnet from network_resources().
                # RDS requires >=2 subnets in different AZs for production clusters;
                # follow-up adds EmsSubnetB in a second AZ to network_resources().
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnet"}],
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
    }
