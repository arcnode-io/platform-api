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

from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
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
        deployment_context: DeploymentContext,
    ) -> str:
        """Return the per-order CFN template (yaml) with all inputs baked in."""
        short = deployment_uuid.split("-", 1)[0]
        userdata = build_userdata(
            deployment_uuid=deployment_uuid,
            dtm_url=dtm_url,
            ems_mode=ems_mode,
            deployment_context=deployment_context,
        )
        persistence = self._persistence.build(
            deployment_context=deployment_context,
        )
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"ARCNODE EMS deployment — {deployment_uuid}",
            "Parameters": persistence.parameters,
            "Resources": {
                **network_resources(),
                **iam_resources(short=short),
                **persistence.resources,
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    "DependsOn": persistence.ems_instance_depends_on,
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
        return yaml.safe_dump(template, sort_keys=False)
