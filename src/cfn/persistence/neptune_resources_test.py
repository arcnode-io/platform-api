"""Unit tests for Neptune Serverless CFN resource builder."""

from src.cfn.persistence.neptune_resources import neptune_resources


def test_neptune_resources_returns_dict_with_expected_keys() -> None:
    """Resource block contains cluster + instance + subnet group + SG + SSM param."""
    # Arrange + Act
    resources = neptune_resources()

    # Assert
    assert set(resources.keys()) == {
        "NeptuneSubnetGroup",
        "NeptuneSecurityGroup",
        "NeptuneCluster",
        "NeptuneInstance",
        "NeptuneHostParam",
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
