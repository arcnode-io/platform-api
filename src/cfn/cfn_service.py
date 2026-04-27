"""CfnService — renders the per-order CloudFormation template.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url /
ems_mode baked in. Three managed-service connection strings (Neon, Neo4j
Aura, TimescaleDB) are required CFN parameters with no defaults — CFN
refuses to deploy if any are missing. Operators sign up for those three
services first (the portal page lists them as prereqs), then run
`aws cloudformation create-stack` (or upload via Console) and paste in
the connection strings.

v0 stub-real: single EC2 + UserData runs docker-compose with the EMS core
triplet (device-api + hmi + industrial-gateway) pulled from arcnode-io's
GitLab Container Registry. Cross-account DTM fetch + multi-region AMI
lookup are follow-ups; ISO path (self-hosts all three services at
localhost) is out of v1 scope.
"""

import yaml

from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
    persistence_parameters,
)


class CfnService:
    """Per-order CloudFormation template renderer."""

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
            "Parameters": persistence_parameters(),
            "Resources": {
                **network_resources(),
                **iam_resources(short=short),
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    "Properties": {
                        "InstanceType": "t3.medium",
                        "ImageId": AMI_SSM_PARAMETER,
                        "IamInstanceProfile": {"Ref": "EmsInstanceProfile"},
                        "SubnetId": {"Ref": "EmsSubnet"},
                        "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
                        # Fn::Sub substitutes the three ConnectionString params
                        # into the script before CFN base64-encodes it.
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
