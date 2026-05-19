"""arcnode-gc — daily safety-net sweep for orphan smoke resources.

Catches leaks that test fixtures miss: SIGKILL'd test runners, CFN
DeletionPolicy=Retain survivors, non-CFN secrets created by bootstrap
Lambdas, and any other resource that bills while orphaned.

Sweep targets (all >MAX_AGE_HOURS old):
  - CloudFormation stacks named arcnode-smoke-* or smoke-defense-*
  - Secrets Manager secrets named arcnode-ems-* whose owning stack is gone
  - SSM parameters under /arcnode-ems/ whose owning stack is gone

Idempotent. Logs every action. Exits 0 even on partial failures so a
single AWS hiccup doesn't skip the next category.
"""

# ruff: noqa: ANN401, ARG001 — Lambda runtime ABI uses Any/event
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_AGE_HOURS = 6
STACK_NAME_PATTERNS = ("arcnode-smoke-", "smoke-defense-", "smoke-ci-")
SECRET_NAME_PREFIX = "arcnode-ems-"  # noqa: S105 — name prefix, not a secret value
SSM_PATH_PREFIX = "/arcnode-ems/"

ALIVE_STACK_STATUSES = [
    "CREATE_IN_PROGRESS",
    "CREATE_COMPLETE",
    "CREATE_FAILED",
    "ROLLBACK_IN_PROGRESS",
    "ROLLBACK_COMPLETE",
    "UPDATE_IN_PROGRESS",
    "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_IN_PROGRESS",
    "UPDATE_ROLLBACK_COMPLETE",
    "DELETE_IN_PROGRESS",
    "DELETE_FAILED",
]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """EventBridge cron entry point. Returns a summary of actions taken."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)

    cfn = boto3.client("cloudformation")
    sm = boto3.client("secretsmanager")
    ssm = boto3.client("ssm")

    actions: list[str] = []
    active_stack_names = _list_alive_stack_names(cfn)

    _sweep_stacks(cfn, cutoff, actions, active_stack_names)
    _sweep_secrets(sm, cutoff, actions, active_stack_names)
    _sweep_ssm_params(ssm, cutoff, actions, active_stack_names)

    summary = {
        "swept": len(actions),
        "actions": actions,
        "ran_at": now.isoformat(),
    }
    logger.info(json.dumps(summary))
    return summary


def _list_alive_stack_names(cfn: Any) -> set[str]:
    names: set[str] = set()
    for page in cfn.get_paginator("list_stacks").paginate(
        StackStatusFilter=ALIVE_STACK_STATUSES
    ):
        for s in page.get("StackSummaries", []):
            names.add(s["StackName"])
    return names


def _sweep_stacks(
    cfn: Any,
    cutoff: datetime,
    actions: list[str],
    active_stack_names: set[str],
) -> None:
    """Delete arcnode-smoke-* stacks older than cutoff."""
    for page in cfn.get_paginator("list_stacks").paginate(
        StackStatusFilter=ALIVE_STACK_STATUSES
    ):
        for s in page.get("StackSummaries", []):
            name = s["StackName"]
            if not _matches_smoke_pattern(name):
                continue
            if s["CreationTime"] >= cutoff:
                continue
            # Already deleting? Skip — CFN handles the rest.
            if s["StackStatus"] == "DELETE_IN_PROGRESS":
                continue
            try:
                cfn.delete_stack(StackName=name)
                actions.append(f"stack:delete:{name}")
                active_stack_names.discard(name)
            except Exception:
                logger.exception("failed to delete stack %s", name)


def _sweep_secrets(
    sm: Any,
    cutoff: datetime,
    actions: list[str],
    active_stack_names: set[str],
) -> None:
    """Force-delete arcnode-ems-<stack>/* secrets when owning stack is gone."""
    for page in sm.get_paginator("list_secrets").paginate():
        for sec in page.get("SecretList", []):
            name = sec["Name"]
            if not name.startswith(SECRET_NAME_PREFIX):
                continue
            stack_name = _extract_stack_from_secret_name(name)
            if stack_name in active_stack_names:
                continue
            if sec.get("CreatedDate") and sec["CreatedDate"] >= cutoff:
                continue
            try:
                sm.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
                actions.append(f"secret:delete:{name}")
            except Exception:
                logger.exception("failed to delete secret %s", name)


def _sweep_ssm_params(
    ssm: Any,
    cutoff: datetime,
    actions: list[str],
    active_stack_names: set[str],
) -> None:
    """Delete /arcnode-ems/<stack>/* SSM params when owning stack is gone."""
    for page in ssm.get_paginator("describe_parameters").paginate(
        ParameterFilters=[
            {"Key": "Name", "Option": "BeginsWith", "Values": [SSM_PATH_PREFIX]}
        ]
    ):
        for p in page.get("Parameters", []):
            name = p["Name"]
            stack_name = _extract_stack_from_ssm_name(name)
            if stack_name in active_stack_names:
                continue
            if p.get("LastModifiedDate") and p["LastModifiedDate"] >= cutoff:
                continue
            try:
                ssm.delete_parameter(Name=name)
                actions.append(f"ssm:delete:{name}")
            except Exception:
                logger.exception("failed to delete ssm param %s", name)


def _matches_smoke_pattern(name: str) -> bool:
    return any(name.startswith(p) for p in STACK_NAME_PATTERNS)


def _extract_stack_from_secret_name(name: str) -> str:
    """arcnode-ems-<stack>/<slot> → <stack>."""
    rest = name.removeprefix(SECRET_NAME_PREFIX)
    return rest.split("/", 1)[0]


def _extract_stack_from_ssm_name(name: str) -> str:
    """/arcnode-ems/<stack>/<slot> → <stack>."""
    rest = name.removeprefix(SSM_PATH_PREFIX)
    return rest.split("/", 1)[0]
