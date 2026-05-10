"""Unit tests for `aurora_resources.aurora_cluster_resources`.

Asserts presence of the CFN resources Aurora needs (cluster, instance,
master secret, subnet group, security group) and the scale-to-0 +
serverless-v2-config invariants.
"""

from src.cfn.persistence.aurora_resources import aurora_cluster_resources


def test_returns_cluster_instance_and_master_secret() -> None:
    """Three logical IDs: AuroraCluster, AuroraInstance, AuroraMasterSecret."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraCluster" in resources
    assert "AuroraInstance" in resources
    assert "AuroraMasterSecret" in resources


def test_cluster_uses_serverless_with_scale_to_zero() -> None:
    """ServerlessV2ScalingConfiguration with MinCapacity=0 + auto-pause."""
    # Arrange + Act
    cluster = aurora_cluster_resources()["AuroraCluster"]

    # Assert
    assert cluster["Type"] == "AWS::RDS::DBCluster"
    props = cluster["Properties"]
    assert props["Engine"] == "aurora-postgresql"
    assert props["EngineMode"] == "provisioned"
    scaling = props["ServerlessV2ScalingConfiguration"]
    assert scaling["MinCapacity"] == 0
    assert scaling["SecondsUntilAutoPause"] == 300


def test_instance_uses_db_serverless_class() -> None:
    """Instance class is db.serverless (the serverless-v2 class name)."""
    # Arrange + Act
    instance = aurora_cluster_resources()["AuroraInstance"]

    # Assert
    assert instance["Type"] == "AWS::RDS::DBInstance"
    assert instance["Properties"]["DBInstanceClass"] == "db.serverless"


def test_master_secret_is_aws_secretsmanager_secret() -> None:
    """Master credentials live in Secrets Manager, referenced from the cluster."""
    # Arrange + Act
    secret = aurora_cluster_resources()["AuroraMasterSecret"]

    # Assert
    assert secret["Type"] == "AWS::SecretsManager::Secret"
    gen = secret["Properties"]["GenerateSecretString"]
    assert gen["SecretStringTemplate"] == '{"username": "ems_master"}'
    assert gen["GenerateStringKey"] == "password"


def test_returns_subnet_group_and_security_group() -> None:
    """Aurora needs a subnet group + SG; both reference the existing VPC."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraSubnetGroup" in resources
    assert "AuroraSecurityGroup" in resources
    assert resources["AuroraSubnetGroup"]["Type"] == "AWS::RDS::DBSubnetGroup"
    assert resources["AuroraSecurityGroup"]["Type"] == "AWS::EC2::SecurityGroup"
