"""CfnService — renders the per-order CloudFormation template.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url /
ems_mode baked in. Variant is derived from the order's DeploymentContext and
threaded into PersistenceService, which publishes the variant's Resources +
Parameters + EmsInstance DependsOn list.

  - COMMERCIAL → Aurora (doc + vector) + 2 customer-supplied URL params
    (Tiger + Aura) stored as CFN-native Secrets Manager secrets.
  - SOVEREIGN_GOVERNMENT or DEFENSE_FORWARD → Aurora (doc + vector +
    timeseries via pg_partman) + Neptune Serverless + AOSS — all
    CFN-provisioned, zero customer params.

EC2 UserData branches on variant to fetch the right secret slots from
Secrets Manager + SSM Parameter Store at boot.
"""

import yaml

from src.cfn.bedrock_models import description_prereq_clause
from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
)
from src.cfn.persistence.bedrock_preflight_resources import (
    bedrock_preflight_resources,
)
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext


class CfnService:
    """Per-order CloudFormation template renderer."""

    def __init__(self, persistence: PersistenceService) -> None:
        self._persistence = persistence

    def render_template(
        self,
        *,
        deployment_uuid: str,
        dtm_url: str,
        ems_mode: str,
        site_id: str,
        wholesale_market: str,
        settlement_point: str,
        deployment_context: DeploymentContext,
    ) -> str:
        """Return the per-order CFN template (yaml) with all inputs baked in.

        ``site_id`` is the slugified ConfiguratorPayload.deployment_site_name.
        Flows into config.env on EC2 boot and overrides the gateway's baked
        cfg.yml default — every customer publishes to ``sites/{site_id}/...``.

        ``wholesale_market`` + ``settlement_point`` scope analyst-server's
        LMP queries — flow into config.env so the agent's system prompt
        can pin queries to the customer's market without LLM-side guessing.
        """
        short = deployment_uuid.split("-", 1)[0]
        userdata = build_userdata(
            deployment_uuid=deployment_uuid,
            dtm_url=dtm_url,
            ems_mode=ems_mode,
            site_id=site_id,
            wholesale_market=wholesale_market,
            settlement_point=settlement_point,
            deployment_context=deployment_context,
        )
        persistence = self._persistence.build(
            deployment_context=deployment_context,
            short=short,
        )
        # CFN Description is the first thing operators see in the AWS console
        # before deploying — surface the Bedrock prereq here so they don't get
        # a runtime AccessDeniedException after the stack is up. Sourced from
        # bedrock_models so a model deprecation bumps in one place.
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": (
                f"ARCNODE EMS deployment — {deployment_uuid}"
                f"{description_prereq_clause()}"
            ),
            "Parameters": persistence.parameters,
            "Resources": {
                **network_resources(),
                **iam_resources(short=short, deployment_context=deployment_context),
                # Preflight Bedrock model access before any other resource
                # spins up — fails fast with a console link rather than
                # leaving a half-deployed stack hung on persistence wait.
                **bedrock_preflight_resources(),
                **persistence.resources,
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    "DependsOn": [
                        "BedrockPreflightCustomResource",
                        *persistence.ems_instance_depends_on,
                    ],
                    # CFN waits for cfn-signal from UserData before marking
                    # CREATE_COMPLETE. Without this, the stack reports green
                    # the instant the EC2 boots — even if every curl in
                    # UserData failed. 20-minute timeout covers docker
                    # install + image pulls + initial compose-up.
                    "CreationPolicy": {
                        "ResourceSignal": {
                            "Count": 1,
                            "Timeout": "PT20M",
                        },
                    },
                    "Properties": {
                        "InstanceType": "t3.medium",
                        "ImageId": AMI_SSM_PARAMETER,
                        "IamInstanceProfile": {"Ref": "EmsInstanceProfile"},
                        "SubnetId": {"Ref": "EmsSubnet"},
                        "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
                        "UserData": {"Fn::Base64": {"Fn::Sub": userdata}},
                        "Tags": [
                            {"Key": "Name", "Value": f"arcnode-{short}"},
                            {
                                "Key": "ArcnodeDeploymentUuid",
                                "Value": deployment_uuid,
                            },
                        ],
                    },
                },
            },
            "Outputs": {
                "PublicIp": {
                    "Value": {"Fn::GetAtt": ["EmsInstance", "PublicIp"]},
                    "Description": "EMS HMI is reachable on http://<PublicIp>/",
                },
                "DeploymentUuid": {"Value": deployment_uuid},
                "DtmUrl": {"Value": dtm_url},
                "EmsMode": {"Value": ems_mode},
            },
        }
        if not template["Parameters"]:
            # CFN tolerates missing Parameters but a literal `{}` looks
            # wrong in the rendered YAML; drop the key entirely for defense.
            del template["Parameters"]
        # width=10000 disables YAML line-fold inside scalar strings, which
        # would otherwise split UserData script lines mid-token and break
        # substring search in tests + downstream CFN UserData consumption.
        return yaml.safe_dump(template, sort_keys=False, width=10000)
