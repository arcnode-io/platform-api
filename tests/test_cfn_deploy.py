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
from tests.fixtures.containers import start_localstack

STACK_NAME: str = "arcnode-cfn-deploy-test"
DEPLOYMENT_UUID: str = "cfn-deploy-test-001"
DTM_URL: str = "https://example.com/dtm.json"
EMS_MODE: str = "sim"

# Realistic-shape placeholder connection strings — CFN needs MinLength=1 to satisfy.
NEON_URL: str = "postgres://user:pass@neon.example/db?sslmode=require"
AURA_URL: str = "neo4j+s://aura.example:7687"
TIMESERIES_URL: str = "postgres://user:pass@timescale.example/telemetry"


def test_cfn_template_deploys_cleanly_against_localstack() -> None:
    """create-stack → CREATE_COMPLETE → outputs match → delete-stack."""
    with start_localstack(services=("cloudformation", "ec2", "iam")) as ls:
        cfn = boto3.client(
            "cloudformation",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",  # noqa: S106
        )

        # Arrange — render the per-order template
        template_body = CfnService().render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
        )

        # Act — create the stack
        cfn.create_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=[
                {"ParameterKey": "NeonConnectionString", "ParameterValue": NEON_URL},
                {"ParameterKey": "AuraConnectionString", "ParameterValue": AURA_URL},
                {
                    "ParameterKey": "TimeseriesConnectionString",
                    "ParameterValue": TIMESERIES_URL,
                },
            ],
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
    with start_localstack(services=("cloudformation", "ec2", "iam")) as ls:
        cfn = boto3.client(
            "cloudformation",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",  # noqa: S106
        )
        template_body = CfnService().render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
        )
        with pytest.raises(Exception) as exc_info:
            cfn.create_stack(
                StackName=f"{STACK_NAME}-missing-params",
                TemplateBody=template_body,
                Parameters=[],  # No params — should fail on the three required ones
                Capabilities=["CAPABILITY_IAM"],
            )
        # CFN raises a ClientError mentioning the missing parameter(s)
        msg = str(exc_info.value).lower()
        assert "param" in msg or "default" in msg, msg
