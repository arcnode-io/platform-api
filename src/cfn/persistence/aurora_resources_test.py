"""Unit tests for `aurora_resources.aurora_cluster_resources`.

Asserts presence of the CFN resources Aurora needs (cluster, instance,
master secret, subnet group, security group) and the scale-to-0 +
serverless-v2-config invariants.
"""

from src.cfn.persistence.aurora_resources import (
    COMMERCIAL_SLICES,
    DEFENSE_SLICES,
    aurora_cluster_resources,
)


def test_commercial_slices_omit_timeseries() -> None:
    """Commercial gets document + vector only — Tiger Cloud owns timeseries."""
    # Assert
    assert COMMERCIAL_SLICES == ("document", "vector")


def test_defense_slices_include_timeseries() -> None:
    """Defense gets document + vector + timeseries (Aurora pg_partman)."""
    # Assert
    assert DEFENSE_SLICES == ("document", "vector", "timeseries")


def test_bootstrap_custom_resource_passes_slices_property() -> None:
    """The CFN custom resource gets the slice list as a Property — Lambda branches on it."""
    # Arrange + Act
    resources = aurora_cluster_resources(slices=DEFENSE_SLICES)

    # Assert
    cr = resources["AuroraBootstrapCustomResource"]
    assert cr["Properties"]["Slices"] == list(DEFENSE_SLICES)


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


def test_returns_bootstrap_lambda_and_custom_resource() -> None:
    """Bootstrap Lambda + IAM role + custom resource trigger."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraBootstrapLambdaRole" in resources
    assert "AuroraBootstrapLambda" in resources
    assert "AuroraBootstrapCustomResource" in resources

    lambda_res = resources["AuroraBootstrapLambda"]
    assert lambda_res["Type"] == "AWS::Lambda::Function"
    assert lambda_res["Properties"]["Runtime"] == "python3.13"
    assert lambda_res["Properties"]["Handler"] == "index.handler"
    # The Lambda runs inside the VPC because it speaks Postgres to private RDS
    assert "VpcConfig" in lambda_res["Properties"]


def test_bootstrap_custom_resource_passes_required_properties() -> None:
    """ClusterEndpoint, MasterSecretArn, DeploymentUuid flow into the Lambda."""
    # Arrange + Act
    cr = aurora_cluster_resources()["AuroraBootstrapCustomResource"]

    # Assert
    assert cr["Type"] == "Custom::AuroraBootstrap"
    props = cr["Properties"]
    assert "ClusterEndpoint" in props
    assert "MasterSecretArn" in props
    assert "DeploymentUuid" in props


def test_bootstrap_lambda_embeds_source_via_zipfile() -> None:
    """Lambda code is the bootstrap source file content as ZipFile."""
    # Arrange + Act
    lambda_res = aurora_cluster_resources()["AuroraBootstrapLambda"]

    # Assert
    code = lambda_res["Properties"]["Code"]
    assert "ZipFile" in code
    # Source file content includes the slice spec table — confirms
    # _load_lambda_source ran and embedded the slice-aware bootstrap.
    assert "SLICE_SPECS" in code["ZipFile"]
    assert "ems_document" in code["ZipFile"]
    assert "ems_vector" in code["ZipFile"]
