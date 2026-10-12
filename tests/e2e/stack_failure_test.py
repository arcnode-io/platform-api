"""A failed stack says why, in the error the test raises, not just its status."""

from typing import cast

import pytest
from mypy_boto3_cloudformation import CloudFormationClient

from tests.e2e import fixtures


class FakeCfn:
    def __init__(self, statuses: list[str], events: list[dict[str, str]]) -> None:
        self._statuses = statuses
        self._events = events

    def describe_stacks(self, **_kwargs: object) -> dict[str, object]:
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return {"Stacks": [{"StackStatus": status}]}

    def describe_stack_events(self, **_kwargs: object) -> dict[str, object]:
        return {"StackEvents": self._events}


def test_a_failed_create_raises_with_the_failed_resource_and_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(fixtures, "POLL_INTERVAL_S", 0)
    events = [
        {
            "LogicalResourceId": "AuroraCluster",
            "ResourceStatus": "CREATE_FAILED",
            "ResourceStatusReason": "Cannot find version 16.4 for aurora-postgresql",
        }
    ]
    cfn = FakeCfn(["CREATE_IN_PROGRESS", "ROLLBACK_IN_PROGRESS"], events)

    # Act + Assert
    with pytest.raises(RuntimeError, match=r"AuroraCluster.*Cannot find version 16\.4"):
        fixtures._wait_for_terminal(
            cast(CloudFormationClient, cfn), "smoke-ci-x", "CREATE", 60
        )
