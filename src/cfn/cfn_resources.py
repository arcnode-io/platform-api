"""Per-order CFN template parts — Parameters, Resources, UserData.

Pure data builders called by `CfnService.render_template`. Splitting them
out keeps the service file thin and lets unit tests target each block.
"""

from typing import Final

from src.cfn.bedrock_models import all_invoke_resources
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
    ("vector-url", "VECTOR_URL"),
    ("timeseries-url", "TIMESERIES_URL"),
    # Agent vendor API key — only OpenWeatherMap remains (ADR-024 + ADR-025).
    # Chat + embed go through Bedrock (cloud) or Ollama (airgapped); no
    # OpenAI / Anthropic direct keys anywhere.
    ("openweathermap-api-key", "OPENWEATHERMAP_API_KEY"),
)
COMMERCIAL_ONLY_URL_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("graph-url", "GRAPH_URL"),
)
# Defense-only SSM params → shell var name. No creds — IAM/sigv4 auth.
# UserData fetches each into a shell var, then writes the graph block
# into analyst-cfg.customer.yml so python-mcp-server picks them up via
# the cfg.graph discriminator (CFG_CUSTOMER_PATH deep-merge).
DEFENSE_ONLY_SSM_PARAMS: Final[tuple[tuple[str, str], ...]] = (
    ("neptune-host", "NEPTUNE_HOST"),
    ("neptune-loader-role-arn", "NEPTUNE_LOADER_ROLE_ARN"),
    ("aoss-host", "AOSS_HOST"),
)
# Broker File RBAC + device-api auth secrets. Variant-agnostic (File RBAC runs
# in every deployment) → fetched into secrets.env on both. The 3 mqtt-* pws
# also feed credentials.xml (the broker's auth store). See auth_secrets.py.
AUTH_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("mqtt-gateway-password", "MQTT_GATEWAY_PASSWORD"),
    ("mqtt-operator-password", "MQTT_OPERATOR_PASSWORD"),
    ("mqtt-viewer-password", "MQTT_VIEWER_PASSWORD"),
    ("mqtt-device-api-password", "MQTT_DEVICE_API_PASSWORD"),
    ("mqtt-telemetry-writer-password", "MQTT_TELEMETRY_WRITER_PASSWORD"),
    ("auth-jwt-secret", "AUTH_JWT_SECRET"),
    ("auth-operator-pw", "AUTH_OPERATOR_PW"),
    ("auth-viewer-pw", "AUTH_VIEWER_PW"),
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
                "GroupDescription": "ARCNODE EMS HMI + analyst-server inbound",
                "VpcId": {"Ref": "EmsVpc"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 80,
                        "ToPort": 80,
                        "CidrIp": "0.0.0.0/0",
                    },
                    # analyst-server health + chat (defense compose binds
                    # 8000:8000). e2e probes /health to prove mcp-server
                    # seed completed.
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 8000,
                        "ToPort": 8000,
                        "CidrIp": "0.0.0.0/0",
                    },
                ],
            },
        },
    }


def _neptune_data_policy(*, short: str) -> dict[str, object]:
    """neptune-db:* on the Neptune cluster ResourceId — defense-only.

    The mcp-server seed_graph_neptune path uses sigv4 to stamp the
    ArcnodeSeedMarker and call StartLoaderJob/GetLoaderJobStatus for
    bulk-loading the pre-baked CSVs from arcnode-public.
    """
    return {
        "PolicyName": f"arcnode-{short}-neptune-data",
        "PolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "neptune-db:ReadDataViaQuery",
                        "neptune-db:WriteDataViaQuery",
                        "neptune-db:DeleteDataViaQuery",
                        "neptune-db:GetEngineStatus",
                        "neptune-db:StartLoaderJob",
                        "neptune-db:GetLoaderJobStatus",
                        # graphiti's NeptuneDriver calls GetPropertygraphSummary
                        # at session-open to discover labels/edge-types.
                        # Without this, search_knowledge / verify_fact /
                        # combined_search all 500 with AccessDeniedException
                        # (Phase 10 smoke 2026-05-16).
                        "neptune-db:GetGraphSummary",
                    ],
                    "Resource": {
                        "Fn::Sub": (
                            "arn:${AWS::Partition}:neptune-db:${AWS::Region}:"
                            "${AWS::AccountId}:"
                            "${NeptuneCluster.ClusterResourceId}/*"
                        ),
                    },
                }
            ],
        },
    }


def _aoss_data_policy(*, short: str) -> dict[str, object]:
    """aoss:APIAccessAll on any collection in this account — defense-only.

    Graphiti's NeptuneDriver hits AOSS for keyword search on graph
    nodes. APIAccessAll is the data-plane action; the data-access
    policy on the collection (in aoss_resources) handles index-level
    grants.

    Resource is scoped by account-arn pattern (not GetAtt on the
    collection) because the AOSS data-access policy already references
    EmsInstanceRole.Arn as a principal — a GetAtt back to the collection
    here would create a circular dep (EmsInstanceRole → AossCollection
    → AossDataAccessPolicy → EmsInstanceRole).
    """
    return {
        "PolicyName": f"arcnode-{short}-aoss-data",
        "PolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "aoss:APIAccessAll",
                    "Resource": {
                        "Fn::Sub": (
                            "arn:${AWS::Partition}:aoss:${AWS::Region}:"
                            "${AWS::AccountId}:collection/*"
                        ),
                    },
                }
            ],
        },
    }


def iam_resources(
    *, short: str, deployment_context: DeploymentContext
) -> dict[str, object]:
    """Instance role with SecretsManager + SSM Parameter Store read for persistence
    plus AmazonSSMManagedInstanceCore so operators can `aws ssm start-session`
    into the EC2 for boot diagnostics without provisioning SSH keys.

    Defense adds Neptune (graph DB-data API) + AOSS (sigv4 against the
    SEARCH collection) policies; commercial leaves them off.
    """
    neptune_data_policy: list[dict[str, object]] = []
    aoss_data_policy: list[dict[str, object]] = []
    if deployment_context != DeploymentContext.COMMERCIAL:
        neptune_data_policy = [_neptune_data_policy(short=short)]
        aoss_data_policy = [_aoss_data_policy(short=short)]
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
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore",
                    },
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
                                            "arn:${AWS::Partition}:secretsmanager:"
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
                                            "arn:${AWS::Partition}:ssm:${AWS::Region}:"
                                            "${AWS::AccountId}:parameter"
                                            "/arcnode-ems/"
                                            "${AWS::StackName}/*"
                                        ),
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "PolicyName": f"arcnode-{short}-bedrock-invoke",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    # Bedrock charges per-token; scope to the
                                    # exact models the analyst uses.
                                    # Sonnet 4.6 via CRIS (us.* prefix) — direct
                                    # anthropic.* IDs require provisioned
                                    # throughput, so we permit ONLY the
                                    # inference-profile + the 3 underlying
                                    # foundation-models the profile spans
                                    # (us-east-1/2 + us-west-2).
                                    # Titan v2 has no CRIS — single FM arn.
                                    "Effect": "Allow",
                                    "Action": [
                                        "bedrock:InvokeModel",
                                        "bedrock:InvokeModelWithResponseStream",
                                    ],
                                    "Resource": all_invoke_resources(),
                                }
                            ],
                        },
                    },
                    {
                        # cfn-signal calls cloudformation:SignalResource at
                        # UserData end. Without this perm the CreationPolicy
                        # on EmsInstance times out + rolls back even on a
                        # clean boot.
                        "PolicyName": f"arcnode-{short}-cfn-signal",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "cloudformation:SignalResource",
                                    "Resource": {
                                        "Fn::Sub": (
                                            "arn:${AWS::Partition}:cloudformation:${AWS::Region}:"
                                            "${AWS::AccountId}:stack/"
                                            "${AWS::StackName}/*"
                                        ),
                                    },
                                }
                            ],
                        },
                    },
                    {
                        # Diagnostic upload — UserData ERR trap writes the
                        # tail of /var/log/cloud-init-output.log here before
                        # cfn-signaling failure. Without this, EC2 terminates
                        # on ROLLBACK + the log dies with it, leaving the
                        # CFN event with just "Received FAILURE signal" (no
                        # context). With it, we curl s3://arcnode-artifacts/
                        # diagnostic/${StackName}/cloud-init.log after a
                        # rollback and see exactly what failed.
                        "PolicyName": f"arcnode-{short}-diagnostic-write",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "s3:PutObject",
                                    "Resource": {
                                        "Fn::Sub": (
                                            "arn:${AWS::Partition}:s3:::"
                                            "arcnode-artifacts/diagnostic/"
                                            "${AWS::StackName}/*"
                                        ),
                                    },
                                }
                            ],
                        },
                    },
                    *neptune_data_policy,
                    *aoss_data_policy,
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
    dtm_url: str,
    site_id: str,
    wholesale_market: str,
    settlement_point: str,
    deployment_context: DeploymentContext,
    e2e: bool = False,
) -> str:
    """Build EC2 UserData. Threads cross-cutting env into config.env and
    writes per-service cfg.customer.yml files (cardinal rule from CLAUDE.md).
    Compose mounts each customer YAML into the matching service and sets
    CFG_CUSTOMER_PATH so the service's loader deep-merges it over the
    baked cfg.defaults.yml. Pattern: analyst-server first; gateway +
    mcp-server migrate as they grow per-deploy config beyond a flag or two.

    ``e2e=True`` writes ``e2e: true`` into analyst-cfg.customer.yml — the
    mcp-server child reads the same file and seeds the small 153-node
    graph fixture instead of the full 96MB dump (CI speed + determinism).
    """
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
    # `variant` drives which compose path we fetch from arcnode-public.
    # Not propagated as an env var into containers — the per-variant
    # compose file already wires the right services.
    variant = (
        "commercial"
        if deployment_context == DeploymentContext.COMMERCIAL
        else "defense"
    )
    url_slots = list(COMMON_URL_SLOTS)
    is_commercial = deployment_context == DeploymentContext.COMMERCIAL
    if is_commercial:
        url_slots.extend(COMMERCIAL_ONLY_URL_SLOTS)
    # Broker + human auth secrets land in secrets.env on every variant.
    url_slots.extend(AUTH_SLOTS)

    # e2e deployments seed the small graph fixture; empty for production.
    e2e_line = "e2e: true\n" if e2e else ""

    # secrets.env — credential-bearing connection URLs from Secrets Manager.
    # Each line writes one ENV_VAR=<URL>.
    secret_lines = "\n".join(
        f'echo "{env_name}=$(aws secretsmanager get-secret-value '
        f"--secret-id arcnode-ems-${{AWS::StackName}}/{slot} "
        f'--query SecretString --output text)" >> /opt/arcnode/secrets.env'
        for slot, env_name in url_slots
    )
    # Broker File RBAC store. The 3 random machine pws (also in secrets.env)
    # are fetched into shell vars and written into credentials.xml, which the
    # hivemq image bind-mounts into the File RBAC extension. Topic ACL is
    # static (system_adr §9 topic shape); only the <password> values vary.
    # ${{AWS::StackName}} is CFN-substituted; $GW_PW/$OP_PW/$VW_PW are bash
    # vars (no braces → Fn::Sub leaves them for the unquoted heredoc to expand).
    credentials_block = (
        "GW_PW=$(aws secretsmanager get-secret-value "
        "--secret-id arcnode-ems-${AWS::StackName}/mqtt-gateway-password "
        "--query SecretString --output text)\n"
        "OP_PW=$(aws secretsmanager get-secret-value "
        "--secret-id arcnode-ems-${AWS::StackName}/mqtt-operator-password "
        "--query SecretString --output text)\n"
        "VW_PW=$(aws secretsmanager get-secret-value "
        "--secret-id arcnode-ems-${AWS::StackName}/mqtt-viewer-password "
        "--query SecretString --output text)\n"
        "DA_PW=$(aws secretsmanager get-secret-value "
        "--secret-id arcnode-ems-${AWS::StackName}/mqtt-device-api-password "
        "--query SecretString --output text)\n"
        "TW_PW=$(aws secretsmanager get-secret-value "
        "--secret-id arcnode-ems-${AWS::StackName}/mqtt-telemetry-writer-password "
        "--query SecretString --output text)\n"
        "cat > /opt/arcnode/credentials.xml <<XML\n"
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<file-rbac>\n"
        "  <users>\n"
        "    <user><name>arcnode_gateway</name><password>$GW_PW</password>"
        "<roles><id>gateway</id></roles></user>\n"
        "    <user><name>arcnode_operator</name><password>$OP_PW</password>"
        "<roles><id>operator</id></roles></user>\n"
        "    <user><name>arcnode_viewer</name><password>$VW_PW</password>"
        "<roles><id>viewer</id></roles></user>\n"
        "    <user><name>arcnode_device_api</name><password>$DA_PW</password>"
        "<roles><id>device_api</id></roles></user>\n"
        "    <user><name>arcnode_telemetry_writer</name><password>$TW_PW</password>"
        "<roles><id>telemetry_writer</id></roles></user>\n"
        "  </users>\n"
        "  <roles>\n"
        # gateway: pub telemetry up, sub commands down, sub system control
        # plane (it subscribes system/topology_changed to hot-reload topology).
        "    <role><id>gateway</id><permissions>"
        "<permission><topic>sites/+/devices/+/measurements/#</topic>"
        "<activity>PUBLISH</activity></permission>"
        "<permission><topic>sites/+/devices/+/commands/#</topic>"
        "<activity>SUBSCRIBE</activity></permission>"
        "<permission><topic>system/#</topic>"
        "<activity>SUBSCRIBE</activity></permission>"
        "</permissions></role>\n"
        # device_api: publishes system/topology_changed when topology mutates.
        "    <role><id>device_api</id><permissions>"
        "<permission><topic>system/#</topic>"
        "<activity>PUBLISH</activity></permission>"
        "</permissions></role>\n"
        # telemetry_writer: subscribes all measurements → persists to timeseries.
        "    <role><id>telemetry_writer</id><permissions>"
        "<permission><topic>sites/+/devices/+/measurements/#</topic>"
        "<activity>SUBSCRIBE</activity></permission>"
        "</permissions></role>\n"
        "    <role><id>operator</id><permissions>"
        "<permission><topic>sites/+/devices/+/commands/#</topic>"
        "<activity>PUBLISH</activity></permission>"
        "<permission><topic>sites/+/devices/+/measurements/#</topic>"
        "<activity>SUBSCRIBE</activity></permission>"
        "</permissions></role>\n"
        "    <role><id>viewer</id><permissions>"
        "<permission><topic>sites/+/devices/+/measurements/#</topic>"
        "<activity>SUBSCRIBE</activity></permission>"
        "</permissions></role>\n"
        "  </roles>\n"
        "</file-rbac>\n"
        "XML\n"
        "chmod 600 /opt/arcnode/credentials.xml\n"
    )
    # Defense graph block — fetch SSM params into shell vars, append to
    # the analyst cfg so python-mcp-server's cfg.graph discriminator
    # resolves to NeptuneGraph. Empty string for commercial.
    if is_commercial:
        graph_block = ""
    else:
        ssm_fetches = "\n".join(
            f"{env_name}=$(aws ssm get-parameter "
            f"--name /arcnode-ems/${{AWS::StackName}}/{slot} "
            f"--query Parameter.Value --output text)"
            for slot, env_name in DEFENSE_ONLY_SSM_PARAMS
        )
        graph_block = (
            f"{ssm_fetches}\n"
            "cat >> /opt/arcnode/analyst-cfg.customer.yml <<YML\n"
            "graph:\n"
            "  backend: neptune\n"
            "  neptune_host: $NEPTUNE_HOST\n"
            "  aoss_host: $AOSS_HOST\n"
            "  loader_role_arn: $NEPTUNE_LOADER_ROLE_ARN\n"
            "YML"
        )
    # Init scripts: previously /opt/arcnode/init-scripts/telemetry_writer.py
    # was curl-fetched + bind-mounted into a python:3.13-alpine container
    # that did `pip install paho-mqtt psycopg2-binary` at startup. Replaced
    # by the public ECR image ems-telemetry-writer (built from
    # src/compose/images/telemetry-writer/Dockerfile) — script + deps baked
    # in. No UserData fetch needed. All data seeding (vector, graph, ercot)
    # lives in consumer services (mcp-server in analyst-server seeds vector +
    # graph; analyst-model seeds ercot).
    # Observability config (prometheus + grafana provisioning) compose
    # mounts at /opt/arcnode/observability/. mlflow gets its own data
    # dirs; no shipped config (sqlite + filesystem artifact root, set
    # in compose `command:`).
    observability_files = ["prometheus.yml"]
    observability_lines = "\n".join(
        f"curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused {ARCNODE_PUBLIC_BASE_URL}/observability/{f} "
        f"-o /opt/arcnode/observability/{f}"
        for f in observability_files
    )
    # CFN signaling — without cfn-signal the stack reports CREATE_COMPLETE
    # the instant the AMI boots, even if every curl in UserData fails. Both
    # Phase 5 smokes (2026-05-15, 2026-05-16) hit silent UserData failures
    # while CFN reported green. The trap + signal-resource wraps the whole
    # script: any non-zero exit signals FAILURE → stack rolls back instead
    # of leaving a half-deployed instance behind.
    #
    # AL2023 doesn't ship aws-cfn-bootstrap; install via dnf (NOT pip — the
    # PyPI `aws-cfn-bootstrap` is the 2014 python2 build, lands `cfn-signal`
    # nowhere usable). dnf installs at /usr/bin/cfn-signal.
    # set -u/-o pipefail BEFORE the trap; set -e AFTER so install failures
    # don't silently skip the trap.
    return (
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        "dnf install -y aws-cfn-bootstrap\n"
        # On UserData failure: upload the full cloud-init log to S3
        # (arcnode-artifacts/diagnostic/<stack>/cloud-init.log) BEFORE
        # cfn-signal. Without this, EC2 terminates with ROLLBACK and the
        # log dies — leaving the CFN event as just "Received FAILURE
        # signal" with zero diagnostic. (cfn-signal --reason was tried
        # first — the SignalResource API has no Reason param, the flag
        # is silently ignored.) IAM role `arcnode-{short}-diagnostic-
        # write` grants the upload. Pipeline 2562999614 stack
        # smoke-ci-659de46a was the case that motivated this.
        "_signal_failure() {\n"
        "  aws s3 cp /var/log/cloud-init-output.log "
        "s3://arcnode-artifacts/diagnostic/${AWS::StackName}/cloud-init.log "
        "--region ${AWS::Region} || true\n"
        "  /usr/bin/cfn-signal -e 1 "
        "--stack ${AWS::StackName} --resource EmsInstance --region ${AWS::Region}\n"
        "}\n"
        "trap _signal_failure ERR\n"
        "set -e\n"
        "mkdir -p /opt/arcnode/observability/prometheus-data "
        "/opt/arcnode/observability/grafana-data /opt/arcnode/observability/grafana-provisioning "
        "/opt/arcnode/mlflow/mlflow-data /opt/arcnode/mlflow/mlflow-artifacts\n"
        "# config.env — non-secret config (deployment metadata + IAM-auth hostnames).\n"
        "cat > /opt/arcnode/config.env <<ENV\n"
        "AWS_REGION=${AWS::Region}\n"
        "AWS_DEFAULT_REGION=${AWS::Region}\n"
        "ENV\n"
        # analyst-server's cfg.customer.yml — site_id + market scope per
        # ConfiguratorPayload. ems-analyst-agent's loader merges this over
        # cfg.defaults.yml at startup; the mcp-server child reads the same
        # file, so `e2e: true` flows through to the seed-fixture choice.
        "cat > /opt/arcnode/analyst-cfg.customer.yml <<YML\n"
        f"site_id: {site_id}\n"
        f"market:\n"
        f"  wholesale_market: {wholesale_market}\n"
        f"  settlement_point: {settlement_point}\n"
        f"{e2e_line}"
        "YML\n"
        # gateway's cfg.customer.yml — only site_id today.
        "cat > /opt/arcnode/gateway-cfg.customer.yml <<YML\n"
        f"site_id: {site_id}\n"
        "YML\n"
        # HMI runtime-config overlay. Unlike gateway/analyst (env-merged via
        # CFG_CUSTOMER_PATH), the HMI is a static SPA — its container's nginx
        # serves this at /cfg.customer.yml and the SPA fetches it at boot.
        # Relative URIs → nginx proxies same-origin to device-api + analyst;
        # empty mqttUri → SPA derives ws(s)://${location.host}/mqtt. Only the
        # deployment-specific keys are set; the rest deep-merge from the baked
        # default block. camelCase matches the HMI's config.ts schema.
        "cat > /opt/arcnode/hmi-cfg.customer.yml <<YML\n"
        f"siteId: {site_id}\n"
        f"deploymentName: {site_id}\n"
        # deviceApiUri /api → nginx strips one segment (device-api routes are
        # bare /auth/*, /topology/*). chatApiUri empty → HMI posts /analyst/chat
        # which nginx passes through un-stripped (analyst route IS /analyst/chat).
        "deviceApiUri: /api\n"
        'chatApiUri: ""\n'
        'mqttUri: ""\n'
        f"{e2e_line}"
        "YML\n"
        f"{graph_block}\n"
        "# secrets.env — credential-bearing connection URLs from Secrets Manager.\n"
        ": > /opt/arcnode/secrets.env\n"
        f"{secret_lines}\n"
        "# Broker File RBAC credentials.xml (bind-mounted into hivemq).\n"
        f"{credentials_block}"
        "# Fetch arcnode-public artifacts (compose + observability config).\n"
        f"curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused {ARCNODE_PUBLIC_BASE_URL}/compose/{variant}/docker-compose.yaml "
        "-o /opt/arcnode/docker-compose.yaml\n"
        f"{observability_lines}\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        "# device-api bind-mounts this file read-only at /app/dtm.json and reads\n"
        "# it on boot per system_adr §22 - fatal here so compose never starts\n"
        "# with a missing/stale DTM.\n"
        f"curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused '{dtm_url}' -o /opt/arcnode/dtm.json\n"
        "# Install docker + compose plugin (Amazon Linux 2023 ships neither).\n"
        "dnf install -y docker\n"
        "systemctl enable --now docker\n"
        "DOCKER_CLI_PLUGINS=/usr/libexec/docker/cli-plugins\n"
        "mkdir -p $DOCKER_CLI_PLUGINS\n"
        "curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused "
        "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 "
        "-o $DOCKER_CLI_PLUGINS/docker-compose\n"
        "chmod +x $DOCKER_CLI_PLUGINS/docker-compose\n"
        "# Start the EMS stack — init containers seed DBs\n"
        "# long-runners (hivemq, device-api, hmi, analyst-*) boot.\n"
        "cd /opt/arcnode && docker compose up -d\n"
        # Give services 60s to settle (or fail) before snapshotting state.
        # Without this, the snapshot catches every container as
        # "Created/Starting" — useless for diagnosis. With it, crashed
        # containers have already exited + show their final logs.
        "sleep 60\n"
        # ALWAYS upload compose state to S3 (pass or fail). UserData
        # signaling SUCCESS doesn't mean the e2e tests will pass —
        # a container that takes 5+ min to crash silently leaves /health
        # unreachable. Compose-state snapshot makes the crash visible.
        # Pipeline 2563217577 hit /health-never-200 with no postmortem.
        "(echo '=== docker compose ps ==='; "
        "docker compose ps; "
        "echo '=== docker compose logs (tail 300) ==='; "
        "docker compose logs --tail 300 --no-color) "
        "> /tmp/compose-state.log 2>&1 || true\n"
        "aws s3 cp /tmp/compose-state.log "
        "s3://arcnode-artifacts/diagnostic/${AWS::StackName}/compose-state.log "
        "--region ${AWS::Region} || true\n"
        "touch /opt/arcnode/userdata.done\n"
        "# Tell CFN we made it — stack will mark EmsInstance CREATE_COMPLETE.\n"
        "/usr/bin/cfn-signal -e 0 --stack ${AWS::StackName} "
        "--resource EmsInstance --region ${AWS::Region}\n"
    )
