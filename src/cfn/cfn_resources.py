"""Per-order CFN template parts — Parameters, Resources, UserData.

Pure data builders called by `CfnService.render_template`. Splitting them
out keeps the service file thin and lets unit tests target each block.
"""

from typing import Final

EMS_REGISTRY: Final[str] = "registry.gitlab.com/arcnode-io"
EMS_SERVICES: Final[tuple[str, ...]] = (
    "ems-device-api",
    "ems-hmi",
    "ems-industrial-gateway",
)
# us-east-1 Amazon Linux 2023 x86_64. Multi-region is a follow-up.
AMI_US_EAST_1: Final[str] = "ami-0c520a2bdcd2f12fd"

# Three managed-service connection strings the operator must supply at
# `aws cloudformation create-stack` time. No defaults → CFN refuses to
# deploy if any are missing. NoEcho keeps them out of the Console UI.
PERSISTENCE_PARAMETERS: Final[tuple[tuple[str, str], ...]] = (
    (
        "NeonConnectionString",
        "Neon Postgres URL (postgres://...?sslmode=require). Covers both "
        "relational config and the pgvector vector store.",
    ),
    (
        "AuraConnectionString",
        "Neo4j Aura URI (neo4j+s://...). Used by the chatbot.",
    ),
    (
        "TimeseriesConnectionString",
        "Time-series store URL (postgres://...). Telemetry persistence.",
    ),
)


def persistence_parameters() -> dict[str, object]:
    """Three required no-default String parameters, NoEcho + MinLength=1."""
    return {
        name: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": description,
        }
        for name, description in PERSISTENCE_PARAMETERS
    }


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


def build_userdata(*, deployment_uuid: str, dtm_url: str, ems_mode: str) -> str:
    """Bash UserData template — Fn::Sub interpolates the connection-string params.

    Each `${ParamName}` is substituted by CloudFormation at deploy time before
    the script runs. The compose body is a single-quoted heredoc so bash
    doesn't try to re-expand anything after CFN is done.
    """
    compose = "".join(
        _compose_block(svc=svc, deployment_uuid=deployment_uuid, ems_mode=ems_mode)
        for svc in EMS_SERVICES
    )
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "dnf install -y docker\n"
        "systemctl enable --now docker\n"
        "mkdir -p /opt/arcnode\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
        "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
        "cat > /opt/arcnode/docker-compose.yml <<'COMPOSE'\n"
        "version: '3.8'\n"
        "services:\n"
        f"{compose}"
        "COMPOSE\n"
        "cd /opt/arcnode && docker compose up -d\n"
    )


def _compose_block(*, svc: str, deployment_uuid: str, ems_mode: str) -> str:
    """One docker-compose service entry. ems-hmi gets the public port."""
    block = (
        f"  {svc}:\n"
        f"    image: {EMS_REGISTRY}/{svc}:latest\n"
        f"    restart: unless-stopped\n"
        f"    environment:\n"
        f"      ARCNODE_DEPLOYMENT_UUID: '{deployment_uuid}'\n"
        f"      ARCNODE_EMS_MODE: '{ems_mode}'\n"
        f"      NEON_DATABASE_URL: '${{NeonConnectionString}}'\n"
        f"      AURA_URI: '${{AuraConnectionString}}'\n"
        f"      TIMESERIES_URL: '${{TimeseriesConnectionString}}'\n"
        f"    volumes:\n"
        f"      - /opt/arcnode/dtm.json:/etc/arcnode/dtm.json:ro\n"
    )
    if svc == "ems-hmi":
        block += "    ports:\n      - '80:80'\n"
    return block
