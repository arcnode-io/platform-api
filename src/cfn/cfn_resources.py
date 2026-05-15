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
# Secrets Manager slot → persistence.env env-var name. Each slot is a
# Postgres / Neo4j connection URL (with embedded credentials); env_file
# consumers parse with their lib's URL constructor.
#
# SMOKE-LEAN: vector slot commented out — defense's PersistenceService
# build skips the analyst-stack vector slice. Restore alongside the
# analyst services + their seed init container.
COMMON_URL_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("document-url", "DOCUMENT_URL"),
    # ("vector-url", "VECTOR_URL"),
    ("timeseries-url", "TIMESERIES_URL"),
)
COMMERCIAL_ONLY_URL_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("graph-url", "GRAPH_URL"),
)
# SSM Parameter Store entries → env-var name. No creds — IAM/sigv4 auth
# via the EC2 instance profile.
#
# SMOKE-LEAN: Neptune + AOSS commented out alongside their CFN resources.
DEFENSE_ONLY_SSM_PARAMS: Final[tuple[tuple[str, str], ...]] = (
    # ("neptune-host", "NEPTUNE_HOST"),
    # ("neptune-loader-role-arn", "NEPTUNE_LOADER_ROLE_ARN"),
    # ("aoss-host", "AOSS_HOST"),
)

# Static artifacts the EMS team publishes per release to arcnode-public.
# UserData fetches them at boot — never per-order, never carry creds.
ARCNODE_PUBLIC_BASE_URL: Final[str] = (
    "https://arcnode-public.s3.us-east-1.amazonaws.com"
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
                "AvailabilityZone": {
                    "Fn::Select": [0, {"Fn::GetAZs": ""}],
                },
            },
        },
        # Second AZ subnet — Neptune + Aurora subnet groups require >=2 AZs.
        # EC2 itself only lives in EmsSubnet; this subnet exists purely to
        # satisfy the multi-AZ requirement for managed-DB subnet groups.
        "EmsSubnetB": {
            "Type": "AWS::EC2::Subnet",
            "Properties": {
                "VpcId": {"Ref": "EmsVpc"},
                "CidrBlock": "10.0.1.0/24",
                "MapPublicIpOnLaunch": True,
                "AvailabilityZone": {
                    "Fn::Select": [1, {"Fn::GetAZs": ""}],
                },
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
        "EmsSubnetBRouteTableAssociation": {
            "Type": "AWS::EC2::SubnetRouteTableAssociation",
            "Properties": {
                "SubnetId": {"Ref": "EmsSubnetB"},
                "RouteTableId": {"Ref": "EmsRouteTable"},
            },
        },
        # VPC endpoints — keep AWS-API traffic on the AWS backbone so the
        # Aurora bootstrap Lambda (which lives in this VPC) can reach
        # Secrets Manager + S3 (CFN-response signaling) without a NAT
        # gateway. Gateway endpoints (S3, DynamoDB) are free; interface
        # endpoints bill ~$0.01/hr per AZ per endpoint.
        "S3VpcEndpoint": {
            "Type": "AWS::EC2::VPCEndpoint",
            "Properties": {
                "VpcId": {"Ref": "EmsVpc"},
                "ServiceName": {
                    "Fn::Sub": "com.amazonaws.${AWS::Region}.s3",
                },
                "VpcEndpointType": "Gateway",
                "RouteTableIds": [{"Ref": "EmsRouteTable"}],
            },
        },
        "SecretsManagerVpcEndpoint": {
            "Type": "AWS::EC2::VPCEndpoint",
            "Properties": {
                "VpcId": {"Ref": "EmsVpc"},
                "ServiceName": {
                    "Fn::Sub": "com.amazonaws.${AWS::Region}.secretsmanager",
                },
                "VpcEndpointType": "Interface",
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnetB"}],
                "SecurityGroupIds": [{"Ref": "VpcEndpointSecurityGroup"}],
                "PrivateDnsEnabled": True,
            },
        },
        "VpcEndpointSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Allow HTTPS from VPC to interface endpoints",
                "VpcId": {"Ref": "EmsVpc"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "CidrIp": "10.0.0.0/16",
                    }
                ],
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


def iam_resources(
    *, short: str, deployment_context: DeploymentContext
) -> dict[str, object]:
    """Instance role with SecretsManager + SSM Parameter Store read for persistence
    plus AmazonSSMManagedInstanceCore so operators can `aws ssm start-session`
    into the EC2 for boot diagnostics without provisioning SSH keys.

    Defense variant additionally needs neptune-db:* (Read/Write/Delete
    DataViaQuery) on the Neptune cluster so the seed-graph init container
    can stamp + read the ArcnodeSeedMarker via boto3 sigv4-auth.
    """
    # SMOKE-LEAN: Neptune is commented out in defense's PersistenceService
    # build, so the policy below has no NeptuneCluster to reference.
    # Restore alongside the Neptune resources when bringing the analyst
    # stack back online.
    neptune_data_policy: list[dict[str, object]] = []
    # if deployment_context != DeploymentContext.COMMERCIAL:
    #     neptune_data_policy = [
    #         {
    #             "PolicyName": f"arcnode-{short}-neptune-data",
    #             "PolicyDocument": {
    #                 "Version": "2012-10-17",
    #                 "Statement": [
    #                     {
    #                         "Effect": "Allow",
    #                         "Action": [
    #                             "neptune-db:ReadDataViaQuery",
    #                             "neptune-db:WriteDataViaQuery",
    #                             "neptune-db:DeleteDataViaQuery",
    #                             "neptune-db:GetEngineStatus",
    #                             "neptune-db:StartLoaderJob",
    #                             "neptune-db:GetLoaderJobStatus",
    #                         ],
    #                         "Resource": {
    #                             "Fn::Sub": (
    #                                 "arn:aws:neptune-db:${AWS::Region}:"
    #                                 "${AWS::AccountId}:"
    #                                 "${NeptuneCluster.ClusterResourceId}/*"
    #                             ),
    #                         },
    #                     }
    #                 ],
    #             },
    #         }
    #     ]
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
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
                ],
                "Policies": [
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
                    *neptune_data_policy,
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
    """UserData: fetch arcnode-public artifacts, write env files, fetch DTM, run compose.

    ``persistence.env`` exposes one env var per persistence slice — the
    full connection URL for each Postgres/Neo4j slot, plus the bare
    hostname for IAM-auth backends (Neptune, AOSS). Each ems-* container
    consumes via ``env_file: /opt/arcnode/persistence.env``.

    The slot list branches on ``deployment_context``:
      - Commercial: 4 URL secrets (document, vector, timeseries, graph)
      - Defense: 3 URL secrets + 3 SSM params (neptune-host, AOSS-host,
        neptune-loader-role-arn)

    arcnode-public artifacts are static across orders — same compose +
    HOCON + init scripts per arcnode release. UserData curls them once
    at first boot.

    ``${AWS::StackName}`` is left intact for CFN ``Fn::Sub`` substitution.
    """
    # `variant` drives which compose / HOCON path we fetch from arcnode-public.
    # Not propagated as an env var into containers — the per-variant compose
    # file's env-var set is itself the signal (presence of GRAPH_URL vs
    # NEPTUNE_HOST), so consumer code just branches on what's there.
    variant = (
        "commercial"
        if deployment_context == DeploymentContext.COMMERCIAL
        else "defense"
    )
    hocon_dir = (
        "commercial-and-iso"
        if deployment_context == DeploymentContext.COMMERCIAL
        else "defense"
    )
    url_slots = list(COMMON_URL_SLOTS)
    ssm_params: list[tuple[str, str]] = []
    if deployment_context == DeploymentContext.COMMERCIAL:
        url_slots.extend(COMMERCIAL_ONLY_URL_SLOTS)
    else:
        ssm_params.extend(DEFENSE_ONLY_SSM_PARAMS)

    # secrets.env — credential-bearing connection URLs from Secrets Manager.
    # Each line writes one ENV_VAR=<URL>.
    secret_lines = "\n".join(
        f'echo "{env_name}=$(aws secretsmanager get-secret-value '
        f"--secret-id arcnode-ems-${{AWS::StackName}}/{slot} "
        f'--query SecretString --output text)" >> /opt/arcnode/secrets.env'
        for slot, env_name in url_slots
    )
    # config.env — non-secret config from SSM Parameter Store + UserData
    # literals (deployment uuid, dtm url, ems mode). No creds in this file.
    ssm_lines = "\n".join(
        f'echo "{env_name}=$(aws ssm get-parameter '
        f"--name /arcnode-ems/${{AWS::StackName}}/{slot} "
        f'--query Parameter.Value --output text)" >> /opt/arcnode/config.env'
        for slot, env_name in ssm_params
    )
    # Init scripts compose mounts at /opt/arcnode/init-scripts/. Variant
    # picks the matching graph seed script (Neo4j Aura vs Neptune loader).
    graph_seed_script = (
        "seed-graph-neo4j.py"
        if deployment_context == DeploymentContext.COMMERCIAL
        else "seed-graph-neptune.py"
    )
    init_scripts = [
        "render_emqx_rule.py",
        "seed-vector.sh",
        "seed-timeseries.sh",
        graph_seed_script,
    ]
    init_script_lines = "\n".join(
        f"curl -fsSL {ARCNODE_PUBLIC_BASE_URL}/init-scripts/{s} "
        f"-o /opt/arcnode/init-scripts/{s}"
        for s in init_scripts
    )
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p /opt/arcnode/init-scripts /opt/arcnode/emqx\n"
        "# config.env — non-secret config (deployment metadata + IAM-auth hostnames).\n"
        "cat > /opt/arcnode/config.env <<ENV\n"
        f"DEPLOYMENT_UUID={deployment_uuid}\n"
        f"EMS_MODE={ems_mode}\n"
        "AWS_REGION=${AWS::Region}\n"
        "AWS_DEFAULT_REGION=${AWS::Region}\n"
        "ENV\n"
        f"{ssm_lines}\n"
        "# secrets.env — credential-bearing connection URLs from Secrets Manager.\n"
        ": > /opt/arcnode/secrets.env\n"
        f"{secret_lines}\n"
        "# Fetch arcnode-public artifacts (compose, HOCON template, init scripts).\n"
        f"curl -fsSL {ARCNODE_PUBLIC_BASE_URL}/compose/{variant}/docker-compose.yaml "
        "-o /opt/arcnode/docker-compose.yaml\n"
        f"curl -fsSL {ARCNODE_PUBLIC_BASE_URL}/emqx/{hocon_dir}/rule.hocon "
        "-o /opt/arcnode/emqx/rule.hocon.tmpl\n"
        f"{init_script_lines}\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        "# device-api bind-mounts this file read-only at /app/dtm.json and reads\n"
        "# it on boot per system_adr §22 - fatal here so compose never starts\n"
        "# with a missing/stale DTM.\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json\n"
        "# Install docker + compose plugin (Amazon Linux 2023 ships neither).\n"
        "dnf install -y docker\n"
        "systemctl enable --now docker\n"
        "DOCKER_CLI_PLUGINS=/usr/libexec/docker/cli-plugins\n"
        "mkdir -p $DOCKER_CLI_PLUGINS\n"
        "curl -fsSL "
        "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 "
        "-o $DOCKER_CLI_PLUGINS/docker-compose\n"
        "chmod +x $DOCKER_CLI_PLUGINS/docker-compose\n"
        "# Start the EMS stack — init containers seed DBs and render emqx\n"
        "# rule, then long-runners (emqx, device-api, hmi, analyst-*) boot.\n"
        "cd /opt/arcnode && docker compose up -d\n"
        "touch /opt/arcnode/userdata.done\n"
    )
