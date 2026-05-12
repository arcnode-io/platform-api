"""Per-order CFN template parts — Parameters, Resources, UserData.

Pure data builders called by `CfnService.render_template`. Splitting them
out keeps the service file thin and lets unit tests target each block.
"""

from typing import Final

from src.orders.configurator_payload import DeploymentContext

# Secret slots (in Secrets Manager) and SSM parameters EC2 UserData fetches
# at boot. Slot naming follows the Q4 lock: `arcnode-ems-{STACK}/<slot>-url`
# for credential-bearing connection strings (Secrets Manager), and
# `/arcnode-ems/{STACK}/<param>-host` for IAM-auth endpoint hostnames (SSM).
COMMON_SECRET_SLOTS: Final[tuple[str, ...]] = (
    "document-url",
    "vector-url",
    "timeseries-url",
)
COMMERCIAL_ONLY_SECRET_SLOTS: Final[tuple[str, ...]] = ("graph-url",)
DEFENSE_ONLY_SSM_PARAMS: Final[tuple[str, ...]] = (
    "neptune-host",
    "aoss-host",
)

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
                                        "Fn::Sub": (
                                            "arn:aws:secretsmanager:"
                                            "${AWS::Region}:${AWS::AccountId}"
                                            ":secret:arcnode-ems-"
                                            "${AWS::StackName}/*"
                                        ),
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "PolicyName": f"arcnode-{short}-ssm-read",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "ssm:GetParameter",
                                        "ssm:GetParameters",
                                    ],
                                    "Resource": {
                                        "Fn::Sub": (
                                            "arn:aws:ssm:${AWS::Region}:"
                                            "${AWS::AccountId}:parameter"
                                            "/arcnode-ems/"
                                            "${AWS::StackName}/*"
                                        ),
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


def build_userdata(
    *,
    deployment_uuid: str,
    dtm_url: str,
    ems_mode: str,
    deployment_context: DeploymentContext,
) -> str:
    """UserData: write deployment env, fetch persistence secrets + SSM, fetch DTM.

    Per-slice connection strings sit in Secrets Manager under
    ``arcnode-ems-{STACK}/<slot>-url``. Neptune and AOSS endpoint
    hostnames (defense only) sit in SSM Parameter Store under
    ``/arcnode-ems/{STACK}/<param>-host`` — they're plain config
    (no creds; auth is IAM/sigv4 via the EC2 instance profile).

    The slot list branches on `deployment_context`:
      - Commercial: document, vector, timeseries, graph (all in Secrets Manager)
      - Defense: document, vector, timeseries (Secrets Manager) + neptune-host,
        aoss-host (SSM)

    Output files land at ``/opt/arcnode/<slot>`` so docker-compose can mount
    or env_file them. ``${AWS::StackName}`` is left intact for CFN
    ``Fn::Sub`` substitution at deploy time.
    """
    secret_slots = list(COMMON_SECRET_SLOTS)
    ssm_params: list[str] = []
    if deployment_context == DeploymentContext.COMMERCIAL:
        secret_slots.extend(COMMERCIAL_ONLY_SECRET_SLOTS)
    else:
        ssm_params.extend(DEFENSE_ONLY_SSM_PARAMS)

    secret_lines = "\n".join(
        f"aws secretsmanager get-secret-value "
        f'--secret-id "arcnode-ems-${{AWS::StackName}}/{slot}" '
        f"--query SecretString --output text > /opt/arcnode/{slot}"
        for slot in secret_slots
    )
    ssm_lines = "\n".join(
        f"aws ssm get-parameter "
        f'--name "/arcnode-ems/${{AWS::StackName}}/{p}" '
        f"--query Parameter.Value --output text > /opt/arcnode/{p}"
        for p in ssm_params
    )
    fetch_block = secret_lines + ("\n" + ssm_lines if ssm_lines else "")
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p /opt/arcnode\n"
        "cat > /opt/arcnode/deployment.env <<ENV\n"
        f"DEPLOYMENT_UUID={deployment_uuid}\n"
        f"DTM_URL={dtm_url}\n"
        f"EMS_MODE={ems_mode}\n"
        "ENV\n"
        "# Fetch persistence connection strings + endpoint hostnames.\n"
        f"{fetch_block}\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
        "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
        "touch /opt/arcnode/userdata.done\n"
    )
