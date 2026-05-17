"""LocalStack-Pro CFN validate-template smoke for the commercial variant.

LocalStack Pro is the only environment that can run
``cloudformation:ValidateTemplate`` against our template — it parses the
YAML, resolves intrinsic functions, and confirms every ``Ref`` /
``Fn::GetAtt`` resolves to a declared resource or parameter. No
resources are actually created, so the test is fast (~5s).

We don't deploy on LocalStack because Aurora cluster + Lambda custom
resource creation is slow and serialized in LocalStack Pro RDS — a real
deploy smoke runs against real AWS pre-release per Q2 lock.

Defense variant uses Neptune (LocalStack Ultimate-tier only) + AOSS
(LocalStack backlog) — its structural correctness is asserted via unit
tests on the rendered template body in ``src/cfn/cfn_service_test.py``.

Skipped (not failed) when ``LOCALSTACK_AUTH_TOKEN`` is absent — keeps
the gate honest on dev machines without Pro.
"""

import os

import boto3
import pytest

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext
from tests.fixtures.containers import start_localstack

STACK_NAME: str = "arcnode-cfn-deploy-commercial"
DEPLOYMENT_UUID: str = "cfn-deploy-test-001"
DTM_URL: str = "https://example.com/dtm.json"
EMS_MODE: str = "sim"


@pytest.mark.skipif(
    "LOCALSTACK_AUTH_TOKEN" not in os.environ,
    reason=(
        "Requires LocalStack Pro for ``cloudformation:ValidateTemplate`` — "
        "community LocalStack stubs ValidateTemplate. "
        "Set LOCALSTACK_AUTH_TOKEN to run."
    ),
)
def test_commercial_template_passes_aws_validate_template() -> None:
    """``cloudformation:ValidateTemplate`` accepts the rendered commercial template.

    AWS's validate-template is the canonical "would CFN accept this?" check:
    parses YAML, evaluates intrinsic functions, confirms every ``Ref`` and
    ``Fn::GetAtt`` resolves. No deploy, no resource creation. Fast (~seconds).

    Asserts the commercial-distinctive parameters surface as 2 NoEcho-tagged
    inputs — proves customer pastes them at create-stack time.
    """
    with start_localstack(services=("cloudformation",)) as ls:
        cfn = boto3.client(
            "cloudformation",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Arrange — render the per-order template (commercial variant).
        # python3.12 because LocalStack's lambda image hasn't picked up 3.13
        # yet (prod uses 3.13). psycopg2 layer ARN omitted — LocalStack
        # can't fetch the public layer at test time.
        template_body = CfnService(
            persistence=PersistenceService(
                lambda_runtime="python3.12",
                psycopg2_layer_arn_template=None,
            ),
        ).render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
            site_id="test_site",
            wholesale_market="ercot",
            settlement_point="HB_NORTH",
            deployment_context=DeploymentContext.COMMERCIAL,
        )

        # Act — ask CFN to validate the template.
        result = cfn.validate_template(TemplateBody=template_body)

        # Assert — the commercial variant declares 2 NoEcho-true params.
        params = {p["ParameterKey"]: p for p in result["Parameters"]}
        assert set(params.keys()) >= {
            "TimeseriesConnectionUrl",
            "GraphConnectionUrl",
        }
        assert params["TimeseriesConnectionUrl"]["NoEcho"] is True
        assert params["GraphConnectionUrl"]["NoEcho"] is True


def test_commercial_create_fails_when_required_params_missing() -> None:
    """No params → CFN refuses to deploy if either URL is absent."""
    with start_localstack(
        services=("cloudformation",),
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
                lambda_runtime="python3.12",
                psycopg2_layer_arn_template=None,
            ),
        ).render_template(
            deployment_uuid=DEPLOYMENT_UUID,
            dtm_url=DTM_URL,
            ems_mode=EMS_MODE,
            site_id="test_site",
            wholesale_market="ercot",
            settlement_point="HB_NORTH",
            deployment_context=DeploymentContext.COMMERCIAL,
        )

        with pytest.raises(Exception) as exc_info:
            cfn.create_stack(
                StackName=f"{STACK_NAME}-missing-params",
                TemplateBody=template_body,
                Parameters=[],
                Capabilities=["CAPABILITY_IAM"],
            )
        msg = str(exc_info.value).lower()
        assert "param" in msg or "default" in msg, msg
