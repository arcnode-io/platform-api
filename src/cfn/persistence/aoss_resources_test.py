"""Unit tests for AOSS CFN resource builder."""

from src.cfn.persistence.aoss_resources import aoss_resources


def test_aoss_resources_returns_dict_with_expected_keys() -> None:
    """Resource block: 3 policies + collection + SSM endpoint param."""
    # Arrange + Act
    resources = aoss_resources()

    # Assert
    assert set(resources.keys()) == {
        "AossEncryptionPolicy",
        "AossNetworkPolicy",
        "AossDataAccessPolicy",
        "AossCollection",
        "AossHostParam",
    }


def test_aoss_collection_is_search_type() -> None:
    """Collection type SEARCH — Graphiti FTS uses Lucene, not vector-search."""
    # Arrange + Act
    collection = aoss_resources()["AossCollection"]

    # Assert
    assert collection["Properties"]["Type"] == "SEARCH"


def test_aoss_collection_standby_disabled_by_default() -> None:
    """Default: standby OFF — 2 OCU floor for the cheapest demo footprint."""
    # Arrange + Act
    collection = aoss_resources()["AossCollection"]

    # Assert
    assert collection["Properties"]["StandbyReplicas"] == "DISABLED"


def test_aoss_collection_standby_enabled_when_requested() -> None:
    """`standby_enabled=True` flips to ENABLED — 4 OCU floor, HA across AZs."""
    # Arrange + Act
    collection = aoss_resources(standby_enabled=True)["AossCollection"]

    # Assert
    assert collection["Properties"]["StandbyReplicas"] == "ENABLED"


def test_aoss_collection_depends_on_all_three_policies() -> None:
    """AOSS requires encryption + network + data-access policies before create."""
    # Arrange + Act
    collection = aoss_resources()["AossCollection"]

    # Assert
    assert set(collection["DependsOn"]) == {
        "AossEncryptionPolicy",
        "AossNetworkPolicy",
        "AossDataAccessPolicy",
    }


def test_aoss_host_param_publishes_to_ssm() -> None:
    """SSM Parameter holds the collection endpoint for EC2 UserData lookup."""
    # Arrange + Act
    param = aoss_resources()["AossHostParam"]

    # Assert
    assert param["Type"] == "AWS::SSM::Parameter"
    assert "arcnode-ems" in param["Properties"]["Name"]["Fn::Sub"]
