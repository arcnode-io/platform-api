"""End-to-end CFN deploy test against LocalStack.

cfn-lint validates schema; `aws cloudformation validate-template` validates
parsing; this test validates that CFN's deploy engine actually accepts the
template — inter-resource references resolve, IAM trust policies parse,
mappings + Fn::Sub interpolate correctly. EC2 is simulated (no real VM)
so UserData isn't executed; that's fine since we already test UserData
content in `src/cfn/cfn_service_test.py`.

Free, repeatable, no AWS bill.
"""

import time

import boto3
import pytest

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_service import PersistenceService
from tests.fixtures.containers import start_localstack

STACK_NAME: str = "arcnode-cfn-deploy-test"
DEPLOYMENT_UUID: str = "cfn-deploy-test-001"
DTM_URL: str = "https://example.com/dtm.json"
EMS_MODE: str = "sim"

# Six vendor-token parameters the operator pastes at create-stack time —
# Lambda custom resources call vendor REST APIs to provision Tiger Cloud
# + Neo4j Aura at stack-create. MinLength=1 in the template, so any
# non-empty placeholder satisfies CFN's parameter validation.
VENDOR_TOKEN_PARAMS: list[dict[str, str]] = [
    {"ParameterKey": "TigerCloudAccessKey", "ParameterValue": "tiger-access-test"},
    {"ParameterKey": "TigerCloudSecretKey", "ParameterValue": "tiger-secret-test"},
    {"ParameterKey": "TigerCloudProjectId", "ParameterValue": "tiger-project-test"},
    {"ParameterKey": "Neo4jAuraClientId", "ParameterValue": "aura-client-id-test"},
    {
        "ParameterKey": "Neo4jAuraClientSecret",
        "ParameterValue": "aura-client-secret-test",
    },
    {"ParameterKey": "Neo4jAuraTenantId", "ParameterValue": "aura-tenant-test"},
]


@pytest.mark.skipif(
    "LOCALSTACK_AUTH_TOKEN" not in __import__("os").environ,
    reason=(
        "Requires LocalStack Pro for: (1) {{resolve:secretsmanager:...}} "
        "dynamic refs, (2) cross-account Lambda layer fetching, (3) reliable "
        "custom-resource Lambda callbacks. Set LOCALSTACK_AUTH_TOKEN to run. "
        "Skipped (not failed) when token absent — structural assertions live "
        "in src/cfn/cfn_service_test.py + per-resource unit tests."
    ),
)
def test_cfn_template_deploys_cleanly_against_localstack() -> None:
    """Pro-only smoke: CFN parses + AuraLambda creates + custom resource invokes.

    What we CAN verify with placeholder vendor tokens:
      - CFN engine accepts the template (no syntax/schema errors)
      - AuraLambdaRole creates (IAM trust policy parses)
      - AuraLambda creates with the requested runtime (lambda image picks
        up python3.12 — wired through PersistenceService)
      - AuraCustomResource invokes the lambda (custom-resource wiring works)
      - The vendor 401 surfaces cleanly as a CREATE_FAILED reason on the
        custom resource (proves the lambda's error path is wired right)

    What we CAN'T verify here:
      - Aurora cluster / bootstrap (LocalStack Pro stops at first failure;
        Aura branch fails fast before Aurora is attempted)
      - Real CFN CREATE_COMPLETE (needs valid Tiger + Aura accounts)
    Those are covered by structural unit tests in cfn_service_test.py and
    by real-AWS smoke tests, not by this fixture.
    """
    with start_localstack(
        services=(
            "cloudformation",
            "ec2",
            "iam",
            "ssm",
            "lambda",
            "secretsmanager",
            "rds",
        ),
        enable_lambda=True,
    ) as ls:
        cfn = boto3.client(
            "cloudformation",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Arrange — render the per-order template. python3.12 because
        # LocalStack's lambda image hasn't picked up 3.13 yet (prod uses 3.13).
        template_body = CfnService(
            persistence=PersistenceService(
                lambda_runtime="python3.12",
                psycopg2_layer_arn_template=None,
            ),
        ).render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
        )

        cfn.create_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=VENDOR_TOKEN_PARAMS,
            Capabilities=["CAPABILITY_IAM"],
        )

        # Poll until terminal state. LocalStack Pro reaches CREATE_FAILED
        # within ~60s once the Aura custom resource 401s.
        deadline = time.time() + 240.0
        terminal = {
            "CREATE_COMPLETE",
            "CREATE_FAILED",
            "ROLLBACK_COMPLETE",
            "ROLLBACK_FAILED",
        }
        while time.time() < deadline:
            status = cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0][
                "StackStatus"
            ]
            if status in terminal:
                break
            time.sleep(2)

        # Pull every CFN event (paginated) so we can assert against the
        # actual resource-state transitions, not just the latest snapshot.
        paginator = cfn.get_paginator("describe_stack_events")
        events: list[dict] = []
        for page in paginator.paginate(StackName=STACK_NAME):
            events.extend(page["StackEvents"])

        completed = {
            e["LogicalResourceId"]
            for e in events
            if e.get("ResourceStatus") == "CREATE_COMPLETE"
        }
        failed_with_reason = {
            e["LogicalResourceId"]: e.get("ResourceStatusReason", "")
            for e in events
            if e.get("ResourceStatus") == "CREATE_FAILED"
            and e["LogicalResourceId"] != STACK_NAME
        }

        # Assert — Aura branch reached its lambda invocation.
        assert (
            "AuraLambdaRole" in completed
        ), f"AuraLambdaRole should have created cleanly; events: {events}"
        assert (
            "AuraLambda" in completed
        ), f"AuraLambda should have created cleanly; events: {events}"

        # Assert — the vendor 401 surfaces with a useful reason. Proves
        # the lambda's error-callback path to CFN is wired correctly.
        aura_failure = failed_with_reason.get("AuraCustomResource", "")
        assert "401" in aura_failure or "Unauthorized" in aura_failure, (
            f"expected AuraCustomResource to fail with 401/Unauthorized "
            f"(placeholder vendor token), got: {aura_failure!r}; "
            f"all failures: {failed_with_reason}"
        )

        # Cleanup — delete-stack so re-runs don't collide on the same name.
        cfn.delete_stack(StackName=STACK_NAME)


def test_cfn_create_fails_when_required_params_missing() -> None:
    """No defaults → CFN refuses to deploy if any of the 3 connection strings are absent."""
    with start_localstack(
        services=(
            "cloudformation",
            "ec2",
            "iam",
            "ssm",
            "lambda",
            "secretsmanager",
            "rds",
        ),
        enable_lambda=True,
    ) as ls:
        cfn = boto3.client(
            "cloudformation",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        template_body = CfnService(
            persistence=PersistenceService(
                lambda_runtime="python3.12", psycopg2_layer_arn_template=None
            ),
        ).render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
        )
        with pytest.raises(Exception) as exc_info:
            cfn.create_stack(
                StackName=f"{STACK_NAME}-missing-params",
                TemplateBody=template_body,
                Parameters=[],  # No params — should fail on the six required vendor tokens
                Capabilities=["CAPABILITY_IAM"],
            )
        # CFN raises a ClientError mentioning the missing parameter(s)
        msg = str(exc_info.value).lower()
        assert "param" in msg or "default" in msg, msg
