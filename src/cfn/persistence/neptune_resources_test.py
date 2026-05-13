"""Unit tests for Neptune Serverless CFN resource builder."""

from src.cfn.persistence.neptune_resources import neptune_resources


def test_neptune_resources_returns_dict_with_expected_keys() -> None:
    """Resource block contains cluster + instance + subnet group + SG + loader role + 2 SSM params."""
    # Arrange + Act
    resources = neptune_resources()

    # Assert
    assert set(resources.keys()) == {
        "NeptuneSubnetGroup",
        "NeptuneSecurityGroup",
        "NeptuneLoaderRole",
        "NeptuneCluster",
        "NeptuneInstance",
        "NeptuneHostParam",
        "NeptuneLoaderRoleArnParam",
    }


def test_neptune_cluster_is_serverless_with_default_ncu_floor() -> None:
    """Default Min/Max NCU = 1.0 / 128.0 — floor + AWS cap."""
    # Arrange + Act
    cluster = neptune_resources()["NeptuneCluster"]

    # Assert
    scaling = cluster["Properties"]["ServerlessScalingConfiguration"]
    assert scaling["MinCapacity"] == 1.0
    assert scaling["MaxCapacity"] == 128.0


def test_neptune_iam_auth_enabled_by_default() -> None:
    """IAM auth — EC2 instance profile signs; no password handling."""
    # Arrange + Act
    cluster = neptune_resources()["NeptuneCluster"]

    # Assert
    assert cluster["Properties"]["IamAuthEnabled"] is True


def test_neptune_host_param_publishes_to_ssm_for_userdata() -> None:
    """SSM Parameter holds the endpoint hostname for EC2 UserData lookup."""
    # Arrange + Act
    param = neptune_resources()["NeptuneHostParam"]

    # Assert
    assert param["Type"] == "AWS::SSM::Parameter"
    assert "arcnode-ems" in param["Properties"]["Name"]["Fn::Sub"]
    assert param["Properties"]["Value"] == {
        "Fn::GetAtt": ["NeptuneCluster", "Endpoint"],
    }


def test_loader_role_trusts_neptune_service_with_arcnode_public_read() -> None:
    """NeptuneLoaderRole assumed by rds.amazonaws.com, reads arcnode-public seed prefix."""
    # Arrange + Act
    role = neptune_resources()["NeptuneLoaderRole"]

    # Assert — assumed by the RDS service (Neptune is part of RDS family)
    statement = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert statement["Principal"]["Service"] == "rds.amazonaws.com"
    # Assert — narrow scope: only arcnode-public/seed/graph-neptune/*
    policy = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert "arn:aws:s3:::arcnode-public/seed/graph-neptune/*" in policy["Resource"]


def test_neptune_cluster_associates_loader_role() -> None:
    """Cluster's AssociatedRoles wires NeptuneLoaderRole so bulk-loader can assume."""
    # Arrange + Act
    cluster = neptune_resources()["NeptuneCluster"]

    # Assert
    assoc = cluster["Properties"]["AssociatedRoles"]
    assert assoc == [{"RoleArn": {"Fn::GetAtt": ["NeptuneLoaderRole", "Arn"]}}]


def test_loader_role_arn_publishes_to_ssm_for_userdata() -> None:
    """SSM Parameter holds the loader role ARN so the seed init container can pass it to StartLoaderJob."""
    # Arrange + Act
    param = neptune_resources()["NeptuneLoaderRoleArnParam"]

    # Assert
    assert param["Type"] == "AWS::SSM::Parameter"
    assert "neptune-loader-role-arn" in param["Properties"]["Name"]["Fn::Sub"]
    assert param["Properties"]["Value"] == {
        "Fn::GetAtt": ["NeptuneLoaderRole", "Arn"],
    }
