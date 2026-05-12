"""CfnService — renders the per-order CloudFormation template.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url /
ems_mode baked in. Variant is derived from the order's DeploymentContext and
threaded into PersistenceService:

  - COMMERCIAL → Aurora (doc + vector) + customer-supplied Tiger + Aura URLs
  - SOVEREIGN_GOVERNMENT or DEFENSE_FORWARD → Aurora (doc + vector +
    timeseries via pg_partman) + Neptune Serverless + AOSS

The Aurora bootstrap Lambda lands the per-slice connection strings in
Secrets Manager; EC2 UserData fetches them at boot. Neptune + AOSS endpoint
hostnames (defense only) land in SSM Parameter Store — they have no creds
and authenticate via IAM.
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
        )
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"ARCNODE EMS deployment — {deployment_uuid}",
            # Parameters block: commercial gets Timeseries + Graph connection
            # URLs; defense has no required params. Both variants accept the
            # optional cost-knob params (ACU min/max, retention, etc.) — those
            # land alongside the persistence resource block in a follow-up.
            "Parameters": {},
            "Resources": {
                **network_resources(),
                **iam_resources(short=short),
                **self._persistence.build_resources(
                    deployment_context=deployment_context,
                ),
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    # Wait for Aurora bootstrap before launching — UserData
                    # fetches per-slice connection strings at boot.
                    "DependsOn": ["AuroraBootstrapCustomResource"],
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
        return yaml.safe_dump(template, sort_keys=False)
