"""CfnService — renders the per-order CloudFormation template.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url /
ems_mode baked in. Six vendor API tokens (Tiger Cloud access+secret+project,
Neo4j Aura client_id+secret+tenant) are required CFN parameters with no
defaults — CFN refuses to deploy if any are missing. The persistence
sub-module's inline-Lambda custom resources use those tokens to provision
Tiger Cloud + Neo4j Aura instances at stack-create time, while Aurora
serverless PG is provisioned natively (no external API call). All resulting
connection strings flow into Secrets Manager and are fetched by EC2 UserData.
"""

import yaml

from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
    vendor_token_parameters,
)
from src.cfn.persistence.persistence_service import PersistenceService


class CfnService:
    """Per-order CloudFormation template renderer."""

    def __init__(self, persistence: PersistenceService) -> None:
        self._persistence = persistence

    def render_template(
        self, *, deployment_uuid: str, dtm_url: str, ems_mode: str
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
            "Parameters": vendor_token_parameters(),
            "Resources": {
                **network_resources(),
                **iam_resources(short=short),
                **self._persistence.build_resources(),
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    # Wait for all three persistence custom resources before
                    # launching — UserData fetches their secrets at boot.
                    "DependsOn": [
                        "AuroraBootstrapCustomResource",
                        "TigerCustomResource",
                        "AuraCustomResource",
                    ],
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
