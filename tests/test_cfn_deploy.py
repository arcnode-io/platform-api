"""End-to-end CFN deploy test against LocalStack.

cfn-lint validates schema; `aws cloudformation validate-template` validates
parsing; this test validates that CFN's deploy engine actually accepts the
template — inter-resource references resolve, IAM trust policies parse,
mappings + Fn::Sub interpolate correctly. EC2 is simulated (no real VM)
so UserData isn't executed; that's fine since we already test UserData
content in `src/cfn/cfn_service_test.py`.

Free, repeatable, no AWS bill.
"""

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
    {"ParameterKey": "Neo4jAuraClientSecret", "ParameterValue": "aura-client-secret-test"},
    {"ParameterKey": "Neo4jAuraTenantId", "ParameterValue": "aura-tenant-test"},
]


@pytest.mark.xfail(
    reason=(
        "LocalStack community can't fully simulate this template: "
        "(1) {{resolve:secretsmanager:...}} dynamic refs are LocalStack Pro; "
        "(2) the public psycopg2 layer ARN can't be fetched from LocalStack "
        "(also Pro); (3) custom-resource lambda success callbacks are flaky "
        "without Pro. Aspirational coverage retained for when LocalStack Pro "
        "is on the table; structural template assertions live in "
        "src/cfn/cfn_service_test.py + per-resource unit tests."
    ),
    strict=False,
)
def test_cfn_template_deploys_cleanly_against_localstack() -> None:
    """create-stack → CREATE_COMPLETE → outputs match → delete-stack."""
    with start_localstack(
        services=("cloudformation", "ec2", "iam", "ssm", "lambda", "secretsmanager", "rds"),
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
            persistence=PersistenceService(lambda_runtime="python3.12", psycopg2_layer_arn_template=None),
        ).render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
        )

        # Act — create the stack
        cfn.create_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=VENDOR_TOKEN_PARAMS,
            Capabilities=["CAPABILITY_IAM"],
        )

        waiter = cfn.get_waiter("stack_create_complete")
        waiter.wait(
            StackName=STACK_NAME,
            WaiterConfig={"Delay": 2, "MaxAttempts": 30},
        )

        # Assert — stack reached CREATE_COMPLETE with the outputs we expect
        described = cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0]
        assert described["StackStatus"] == "CREATE_COMPLETE"
        outputs = {o["OutputKey"]: o["OutputValue"] for o in described["Outputs"]}
        assert outputs["DeploymentUuid"] == DEPLOYMENT_UUID
        assert outputs["DtmUrl"] == DTM_URL
        assert outputs["EmsMode"] == EMS_MODE
        assert "PublicIp" in outputs

        # Cleanup — delete-stack so re-runs don't collide on the same name
        cfn.delete_stack(StackName=STACK_NAME)


def test_cfn_create_fails_when_required_params_missing() -> None:
    """No defaults → CFN refuses to deploy if any of the 3 connection strings are absent."""
    with start_localstack(
        services=("cloudformation", "ec2", "iam", "ssm", "lambda", "secretsmanager", "rds"),
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
            persistence=PersistenceService(lambda_runtime="python3.12", psycopg2_layer_arn_template=None),
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
