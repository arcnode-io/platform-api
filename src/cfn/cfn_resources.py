"""Per-order CFN template parts — Parameters, Resources, UserData.

Pure data builders called by `CfnService.render_template`. Splitting them
out keeps the service file thin and lets unit tests target each block.
"""

from typing import Final

# Latest Amazon Linux 2023 x86_64 AMI in any region. CFN resolves this SSM
# parameter against `--region` at deploy time, so the template is region-portable
# without a Mappings table that would go stale every AMI revision.
AMI_SSM_PARAMETER: Final[str] = (
    "{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64}}"
)
EMS_SERVICES: Final[tuple[str, ...]] = (
    "ems-device-api",
    "ems-hmi",
    "ems-industrial-gateway",
)


def network_resources() -> dict[str, object]:
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


def iam_resources(*, short: str) -> dict[str, object]:
    """Instance role with S3 GetObject (DTM fetch) + SecretsManager read for persistence."""
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
                    },
                    {
                        "PolicyName": f"arcnode-{short}-secrets-read",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "secretsmanager:GetSecretValue",
                                    "Resource": {
                                        "Fn::Sub": "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:ems/*"
                                    },
                                }
                            ],
                        },
                    },
                ],
            },
        },
        "EmsInstanceProfile": {
            "Type": "AWS::IAM::InstanceProfile",
            "Properties": {"Roles": [{"Ref": "EmsInstanceRole"}]},
        },
    }


def build_userdata(*, deployment_uuid: str, dtm_url: str, ems_mode: str) -> str:
    """UserData: write deployment env, fetch persistence secrets, fetch DTM.

    Per-slice connection strings sit in Secrets Manager under
    ``arcnode-ems-{STACK}/{document,vector,timeseries,graph}-url``. Neptune
    and AOSS endpoint hostnames (defense only) sit in SSM Parameter Store
    under ``/arcnode-ems/{STACK}/{neptune,aoss}-host`` — they're plain config
    (no creds; auth is IAM/sigv4 via the EC2 instance profile).

    This function is variant-agnostic — the per-slice secrets are populated
    by the Aurora bootstrap Lambda (Aurora slices) or by CFN-native
    `AWS::SecretsManager::Secret` resources (Tiger + Aura URLs on commercial).
    The defense-only SSM parameters are populated by CFN as well.

    NOTE: the actual secret-fetch + SSM-read commands land in a follow-up
    commit alongside the variant-specific resource blocks. This stub keeps
    UserData minimal (env + DTM fetch) so the template still renders.
    """
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p /opt/arcnode\n"
        "cat > /opt/arcnode/deployment.env <<ENV\n"
        f"DEPLOYMENT_UUID={deployment_uuid}\n"
        f"DTM_URL={dtm_url}\n"
        f"EMS_MODE={ems_mode}\n"
        "ENV\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
        "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
        "touch /opt/arcnode/userdata.done\n"
    )
