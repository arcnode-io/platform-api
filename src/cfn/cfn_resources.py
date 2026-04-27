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
    """Pre-launch placeholder UserData — drops marker files in /opt/arcnode/.

    Real docker-compose UserData lands once `registry.gitlab.com/arcnode-io/ems-*`
    images are published. Until then this writes deployment metadata + the three
    connection-string params (via Fn::Sub) to disk so an operator can SSH/SSM in
    and confirm UserData ran end-to-end and CFN substitution wired through.
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
        "# Fn::Sub interpolates the three connection-string params before bash runs.\n"
        'echo "${NeonConnectionString}" > /opt/arcnode/neon.url\n'
        'echo "${AuraConnectionString}" > /opt/arcnode/aura.url\n'
        'echo "${TimeseriesConnectionString}" > /opt/arcnode/timeseries.url\n'
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
        "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
        "touch /opt/arcnode/userdata.done\n"
    )
