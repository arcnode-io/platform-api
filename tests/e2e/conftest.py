"""Fixtures for real-AWS e2e tests.

Deploys a commercial stack with the industrial-fixtures DTM, yields the
stack identity to the test, tears down on session end. Scoped by
SITE_ID = ci_<pipeline-id>-<rand> so concurrent CI runs don't collide
on Tiger Cloud rows.

Required env (CI provides via GitLab masked vars; local devs export):
  AWS_REGION                       — defaults to us-east-1
  AURA_CONNECTION_STRING           — Aura URL
  TIGERDATA_CONNECTION_STRING      — Tiger URL (psql-compatible)
  CI_PIPELINE_ID                   — provided by GitLab; falls back to a uuid
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from typing import Final

import boto3
import psycopg2
import psycopg2.extensions
import pytest
from mypy_boto3_cloudformation import CloudFormationClient

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext

AWS_REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")
DTM_URL: Final[str] = (
    "https://arcnode-public.s3.us-east-1.amazonaws.com/seed/industrial-fixtures.json"
)
# 25min covers Aurora ~5min + Lambda CR ~30s + EC2 boot + image pulls.
STACK_READY_TIMEOUT_S: Final[int] = 1500
STACK_DELETE_TIMEOUT_S: Final[int] = 1800
POLL_INTERVAL_S: Final[int] = 30


@pytest.fixture(scope="session")
def cfn() -> CloudFormationClient:
    return boto3.client("cloudformation", region_name=AWS_REGION)


@pytest.fixture(scope="session")
def aura_url() -> str:
    return os.environ["AURA_CONNECTION_STRING"]


@pytest.fixture(scope="session")
def tiger_url() -> str:
    return os.environ["TIGERDATA_CONNECTION_STRING"]


@pytest.fixture
def site_id() -> str:
    """Unique per-test so concurrent CI doesn't collide on Tiger rows."""
    pid = os.environ.get("CI_PIPELINE_ID", uuid.uuid4().hex[:8])
    return f"ci_{pid}_{uuid.uuid4().hex[:6]}"


@pytest.fixture
def commercial_stack(
    cfn: CloudFormationClient, aura_url: str, tiger_url: str, site_id: str
) -> Iterator[dict[str, str]]:
    """Deploys a commercial smoke stack, yields {name, site_id}, tears down."""
    duid = str(uuid.uuid4())
    stack_name = f"smoke-ci-{duid.split('-')[0]}"

    template = CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=duid,
        dtm_url=DTM_URL,
        site_id=site_id,
        wholesale_market="ercot",
        settlement_point="HB_NORTH",
        deployment_context=DeploymentContext.COMMERCIAL,
    )

    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=template,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[
            {
                "ParameterKey": "OpenweathermapApiKey",
                "ParameterValue": "0" * 32,
            },
            {"ParameterKey": "GraphConnectionUrl", "ParameterValue": aura_url},
            {"ParameterKey": "TimeseriesConnectionUrl", "ParameterValue": tiger_url},
        ],
        Tags=[
            {"Key": "arcnode-smoke", "Value": "ci"},
            {"Key": "auto-teardown", "Value": "true"},
        ],
        OnFailure="ROLLBACK",
    )
    try:
        _wait_for_terminal(cfn, stack_name, "CREATE", STACK_READY_TIMEOUT_S)
        yield {"name": stack_name, "site_id": site_id}
    finally:
        # Idempotent — runs even if create timed out or assertions failed.
        cfn.delete_stack(StackName=stack_name)
        # Don't block test exit on Aurora drain (~15min); CFN tag-cleanup
        # nightly job sweeps any leftover orphans.


def _wait_for_terminal(
    cfn: CloudFormationClient, stack_name: str, op: str, timeout_s: int
) -> None:
    """Poll until the stack is past its IN_PROGRESS state for ``op``."""
    in_progress = f"{op}_IN_PROGRESS"
    success = f"{op}_COMPLETE"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["StackStatus"]
        if status == success:
            return
        if status != in_progress:
            raise RuntimeError(f"stack {stack_name} {op} reached {status}")
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"stack {stack_name} {op} not done after {timeout_s}s")


@pytest.fixture
def tiger_conn(tiger_url: str) -> Iterator[psycopg2.extensions.connection]:
    """Connection to the customer Tiger DB. Caller owns cursor lifecycle."""
    conn = psycopg2.connect(tiger_url)
    try:
        yield conn
    finally:
        conn.close()
