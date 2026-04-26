"""CfnService — renders the per-order CloudFormation template.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url /
ems_mode baked in (no CFN `Parameters:` block — values are known at render
time). The orchestrator uploads the rendered yaml to S3; the portal links
to it for download. Operators run the stack themselves from any partition
with `aws cloudformation create-stack` or via Console upload.

v0 stub-real: single EC2 + UserData runs docker-compose with the EMS core
triplet (device-api + hmi + industrial-gateway) pulled from arcnode-io's
GitLab Container Registry. Provisions its own VPC + public subnet so the
operator runs `create-stack` with no parameter prompts. Cross-account DTM
fetch + multi-region AMI lookup are follow-ups.
"""

from typing import Final

import yaml

EMS_REGISTRY: Final[str] = "registry.gitlab.com/arcnode-io"
EMS_SERVICES: Final[tuple[str, ...]] = (
    "ems-device-api",
    "ems-hmi",
    "ems-industrial-gateway",
)
# us-east-1 Amazon Linux 2023 x86_64. Multi-region is a follow-up.
AMI_US_EAST_1: Final[str] = "ami-0c520a2bdcd2f12fd"


class CfnService:
    """Per-order CloudFormation template renderer."""

    def render_template(
        self, *, deployment_uuid: str, dtm_url: str, ems_mode: str
    ) -> str:
        """Return the per-order CFN template (yaml) with all inputs baked in."""
        short = deployment_uuid.split("-", 1)[0]
        userdata = self._build_userdata(
            deployment_uuid=deployment_uuid,
            dtm_url=dtm_url,
            ems_mode=ems_mode,
        )
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": (f"ARCNODE EMS deployment — {deployment_uuid}"),
            "Mappings": {
                "RegionAmi": {
                    "us-east-1": {"Ami": AMI_US_EAST_1},
                },
            },
            "Resources": {
                **self._network_resources(),
                **self._iam_resources(short=short),
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    "Properties": {
                        "InstanceType": "t3.medium",
                        "ImageId": {
                            "Fn::FindInMap": [
                                "RegionAmi",
                                {"Ref": "AWS::Region"},
                                "Ami",
                            ]
                        },
                        "IamInstanceProfile": {"Ref": "EmsInstanceProfile"},
                        "SubnetId": {"Ref": "EmsSubnet"},
                        "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
                        "UserData": {"Fn::Base64": userdata},
                        "Tags": [
                            {"Key": "Name", "Value": f"arcnode-{short}"},
                            {"Key": "ArcnodeDeploymentUuid", "Value": deployment_uuid},
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

    @staticmethod
    def _network_resources() -> dict[str, object]:
        """Tiny VPC + public subnet so the operator launches without parameters."""
        return {
            "EmsVpc": {
                "Type": "AWS::EC2::VPC",
                "Properties": {
                    "CidrBlock": "10.0.0.0/16",
                    "EnableDnsSupport": True,
                    "EnableDnsHostnames": True,
                },
            },
            "EmsInternetGateway": {"Type": "AWS::EC2::InternetGateway"},
            "EmsVpcGatewayAttachment": {
                "Type": "AWS::EC2::VPCGatewayAttachment",
                "Properties": {
                    "VpcId": {"Ref": "EmsVpc"},
                    "InternetGatewayId": {"Ref": "EmsInternetGateway"},
                },
            },
            "EmsSubnet": {
                "Type": "AWS::EC2::Subnet",
                "Properties": {
                    "VpcId": {"Ref": "EmsVpc"},
                    "CidrBlock": "10.0.0.0/24",
                    "MapPublicIpOnLaunch": True,
                },
            },
            "EmsRouteTable": {
                "Type": "AWS::EC2::RouteTable",
                "Properties": {"VpcId": {"Ref": "EmsVpc"}},
            },
            "EmsDefaultRoute": {
                "Type": "AWS::EC2::Route",
                "DependsOn": "EmsVpcGatewayAttachment",
                "Properties": {
                    "RouteTableId": {"Ref": "EmsRouteTable"},
                    "DestinationCidrBlock": "0.0.0.0/0",
                    "GatewayId": {"Ref": "EmsInternetGateway"},
                },
            },
            "EmsSubnetRouteTableAssociation": {
                "Type": "AWS::EC2::SubnetRouteTableAssociation",
                "Properties": {
                    "SubnetId": {"Ref": "EmsSubnet"},
                    "RouteTableId": {"Ref": "EmsRouteTable"},
                },
            },
            "EmsSecurityGroup": {
                "Type": "AWS::EC2::SecurityGroup",
                "Properties": {
                    "GroupDescription": "ARCNODE EMS HMI inbound",
                    "VpcId": {"Ref": "EmsVpc"},
                    "SecurityGroupIngress": [
                        {
                            "IpProtocol": "tcp",
                            "FromPort": 80,
                            "ToPort": 80,
                            "CidrIp": "0.0.0.0/0",
                        }
                    ],
                },
            },
        }

    @staticmethod
    def _iam_resources(*, short: str) -> dict[str, object]:
        """Instance role with S3 GetObject on platform-api's bucket (DTM fetch)."""
        return {
            "EmsInstanceRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "AssumeRolePolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "ec2.amazonaws.com"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    },
                    "Policies": [
                        {
                            "PolicyName": f"arcnode-{short}-dtm-read",
                            "PolicyDocument": {
                                "Version": "2012-10-17",
                                "Statement": [
                                    {
                                        "Effect": "Allow",
                                        "Action": "s3:GetObject",
                                        "Resource": "*",
                                    }
                                ],
                            },
                        }
                    ],
                },
            },
            "EmsInstanceProfile": {
                "Type": "AWS::IAM::InstanceProfile",
                "Properties": {"Roles": [{"Ref": "EmsInstanceRole"}]},
            },
        }

    @staticmethod
    def _build_userdata(*, deployment_uuid: str, dtm_url: str, ems_mode: str) -> str:
        """Bash UserData: install docker, fetch DTM, run docker-compose with EMS core."""
        compose = "".join(
            CfnService._compose_block(
                svc=svc, deployment_uuid=deployment_uuid, ems_mode=ems_mode
            )
            for svc in EMS_SERVICES
        )
        return (
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "dnf install -y docker\n"
            "systemctl enable --now docker\n"
            "mkdir -p /opt/arcnode\n"
            "# Fetch the Device Topology Manifest. Cross-account read is\n"
            "# pending — operator may need to presign or grant bucket access.\n"
            f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
            "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
            "cat > /opt/arcnode/docker-compose.yml <<'YAML'\n"
            "version: '3.8'\n"
            "services:\n"
            f"{compose}"
            "YAML\n"
            "cd /opt/arcnode && docker compose up -d\n"
        )

    @staticmethod
    def _compose_block(*, svc: str, deployment_uuid: str, ems_mode: str) -> str:
        """One docker-compose service entry. ems-hmi gets the public port."""
        block = (
            f"  {svc}:\n"
            f"    image: {EMS_REGISTRY}/{svc}:latest\n"
            f"    restart: unless-stopped\n"
            f"    environment:\n"
            f"      ARCNODE_DEPLOYMENT_UUID: '{deployment_uuid}'\n"
            f"      ARCNODE_EMS_MODE: '{ems_mode}'\n"
            f"    volumes:\n"
            f"      - /opt/arcnode/dtm.json:/etc/arcnode/dtm.json:ro\n"
        )
        if svc == "ems-hmi":
            block += "    ports:\n      - '80:80'\n"
        return block
