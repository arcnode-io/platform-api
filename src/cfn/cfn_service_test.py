"""Unit tests for `CfnService.render_template`.

Validates the rendered yaml against the CloudFormation spec via cfn-lint
(AST + spec check, no AWS creds) and asserts the structural shape we
need: VPC + IAM + EC2 + UserData that boots docker-compose with the EMS
core triplet (device-api + hmi + industrial-gateway) wired to the three
managed-service connection strings the operator must supply.

Server-side validation (live image pulls, IAM evaluation, real launch)
happens when the operator actually runs the stack — out of scope here.
"""

import pytest
import yaml
from cfnlint import api as cfnlint_api

from src.cfn.cfn_resources import ARCNODE_PUBLIC_BASE_URL
from src.cfn.cfn_service import CfnService
from src.cfn.site_callback import SiteCallback
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext

DEPLOYMENT_UUID: str = "abcd1234-5678-90ef-1234-567890abcdef"
DTM_URL: str = "https://platform-api-artifacts.example/orders/o1/dtm.json"
SITE_ID: str = "test_site"


def _render(
    deployment_context: DeploymentContext = DeploymentContext.COMMERCIAL,
    *,
    e2e: bool = False,
    market_region: str | None = "ercot",
    settlement_point: str | None = "HB_NORTH",
    site_callback: SiteCallback | None = None,
) -> str:
    return CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=DEPLOYMENT_UUID,
        dtm_url=DTM_URL,
        site_id=SITE_ID,
        market_region=market_region,
        settlement_point=settlement_point,
        deployment_context=deployment_context,
        e2e=e2e,
        site_callback=site_callback,
    )


def test_e2e_flag_writes_e2e_true_into_analyst_cfg() -> None:
    """render_template(e2e=True) → `e2e: true` in analyst-cfg.customer.yml.

    The mcp-server child reads that file; the flag makes its seed pull
    the small graph-neo4j-e2e.cypher.gz fixture instead of the 96MB dump.
    """
    # Arrange + Act
    with_e2e = _render(e2e=True)
    without = _render(e2e=False)

    # Assert — flag present only when requested, scoped to the analyst
    # cfg heredoc body (between the `<<YML` opener and its `YML` close).
    analyst_block = with_e2e.split("analyst-cfg.customer.yml")[1]
    heredoc_body = analyst_block.split("YML")[1]
    assert "e2e: true" in heredoc_body
    assert "e2e: true" not in without


def test_no_settlement_point_omits_market_block_from_analyst_cfg() -> None:
    """Grid paths with no settlement point (off-grid, or a market_region not
    yet pinned to a settlement point) pass settlement_point=None —
    analyst-server has no concrete LMP node to query, so the market: block
    is omitted entirely rather than written with null values.
    """
    # Arrange + Act
    without_market = _render(market_region=None, settlement_point=None)
    with_market = _render()

    # Assert
    analyst_block = without_market.split("analyst-cfg.customer.yml")[1]
    heredoc_body = analyst_block.split("YML")[1]
    assert "market:" not in heredoc_body

    # Regression guard — the market block is still there when set
    with_market_block = with_market.split("analyst-cfg.customer.yml")[1].split("YML")[1]
    assert "market:" in with_market_block
    assert "wholesale_market: ercot" in with_market_block
    assert "settlement_point: HB_NORTH" in with_market_block


def test_render_template_passes_cfn_lint() -> None:
    """Rendered yaml has no cfn-lint ERROR-level findings (W warnings tolerated)."""
    # Arrange + Act
    rendered = _render()
    matches = cfnlint_api.lint(rendered)

    # Assert
    errors = [m for m in matches if str(m.rule.id).startswith("E")]
    assert errors == [], "cfn-lint errors:\n" + "\n".join(str(e) for e in errors)


def test_render_template_emits_top_level_cfn_keys() -> None:
    """Top-level keys CFN requires + the per-order Description hint."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AWSTemplateFormatVersion: '2010-09-09'" in rendered
    assert DEPLOYMENT_UUID in rendered


def test_render_template_provisions_vpc_and_subnet() -> None:
    """A self-contained VPC + public subnet so the operator launches with no params."""
    # Arrange + Act
    rendered = _render()

    # Assert — the resource Types CFN needs to lay down a public subnet
    assert "AWS::EC2::VPC" in rendered
    assert "AWS::EC2::Subnet" in rendered
    assert "AWS::EC2::InternetGateway" in rendered
    assert "AWS::EC2::SecurityGroup" in rendered
    assert "AWS::EC2::Route" in rendered


def test_render_template_provisions_instance_role_for_secret_and_ssm_reads() -> None:
    """An IAM role + InstanceProfile so EC2 can read SecretsManager + SSM Parameter Store."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AWS::IAM::Role" in rendered
    assert "AWS::IAM::InstanceProfile" in rendered
    assert "secretsmanager:GetSecretValue" in rendered
    assert "ssm:GetParameter" in rendered


def test_render_template_ec2_instance_wires_to_subnet_iam_and_ssm_ami() -> None:
    """EmsInstance refs the subnet, IAM profile, security group, and SSM AMI lookup."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AWS::EC2::Instance" in rendered
    assert "EmsInstanceProfile" in rendered
    assert "EmsSubnet" in rendered
    assert "EmsSecurityGroup" in rendered
    # SSM resolve syntax — CFN looks up the latest stock AL2023 AMI in --region
    assert (
        "resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
        in rendered
    )
    # No stale top-level Mappings table (anchor to start-of-line so this
    # doesn't false-positive on BlockDeviceMappings: in the EmsInstance).
    assert "\nMappings:" not in rendered


def test_render_template_userdata_installs_docker_and_starts_compose() -> None:
    """UserData bootstraps docker + compose, fetches artifacts, and starts the stack."""
    # Arrange + Act
    rendered = _render(e2e=True)

    # Assert — bash shell + the expected file layout
    assert "#!/bin/bash" in rendered
    assert "/opt/arcnode/config.env" in rendered
    assert "/opt/arcnode/secrets.env" in rendered
    assert "/opt/arcnode/userdata.done" in rendered
    assert DTM_URL in rendered
    # Assert — docker install + compose up wire the EMS stack onto the EC2
    assert "dnf install -y docker" in rendered
    assert "systemctl enable --now docker" in rendered
    assert (
        "docker compose -f docker-compose.yaml -f docker-compose.fixtures.yaml up -d"
        in rendered
    )
    # No reference to the old private registry — images come from ECR Public
    assert "registry.gitlab.com" not in rendered


def test_real_deploy_ships_no_industrial_fixtures() -> None:
    """e2e=False (a real customer deploy): no fixtures overlay fetched or merged.

    system_adr §25 — a real deployment ships every device unprovisioned and
    runs no fixtures. Regression guard for exactly that.
    """
    # Arrange + Act
    rendered = _render(e2e=False)

    # Assert
    assert "docker-compose.fixtures.yaml" not in rendered


def test_e2e_deploy_fetches_and_merges_industrial_fixtures() -> None:
    """e2e=True: fetches the fixtures overlay and merges it in via a second -f."""
    # Arrange + Act
    rendered = _render(e2e=True)

    # Assert
    assert (
        "compose/industrial-fixtures/docker-compose.yaml" in rendered
    ), "fixtures overlay not fetched"
    assert "-o /opt/arcnode/docker-compose.fixtures.yaml" in rendered
    assert (
        "-f docker-compose.yaml -f docker-compose.fixtures.yaml up -d" in rendered
    ), "fixtures overlay not merged into docker compose up"


def test_render_template_userdata_signals_cfn_on_success_and_failure() -> None:
    """cfn-signal must wrap UserData so stack status reflects real boot state.

    Without this, the stack reports CREATE_COMPLETE the instant the EC2
    boots — even if every curl in UserData fails. Both Phase 5 smokes
    in May 2026 hit silent UserData failures while CFN reported green.
    """
    # Arrange + Act
    rendered = _render()

    # Assert — aws-cfn-bootstrap installed via dnf (NOT pip — see comment
    # in cfn_resources.build_userdata). Lands at /usr/bin/cfn-signal.
    assert "dnf install -y aws-cfn-bootstrap" in rendered
    # Trap fires _signal_failure on ANY error — captures last 50 lines
    # of /var/log/cloud-init-output.log and passes via cfn-signal --reason.
    assert "trap _signal_failure ERR" in rendered
    assert "/usr/bin/cfn-signal -e 1" in rendered
    assert "/var/log/cloud-init-output.log" in rendered
    # Success signal at the end
    assert "cfn-signal -e 0" in rendered
    # EmsInstance gates CREATE_COMPLETE on the signal
    assert "CreationPolicy" in rendered
    assert "ResourceSignal" in rendered
    # IAM role has the matching cloudformation:SignalResource permission
    assert "cloudformation:SignalResource" in rendered


def test_render_template_outputs_echo_per_order_inputs() -> None:
    """Outputs include the public IP + the order's params for op visibility."""
    # Arrange + Act
    rendered = _render()

    # Assert — `safe_dump(sort_keys=False)` produces stable `Value:` lines
    assert f"Value: {DEPLOYMENT_UUID}" in rendered
    assert f"Value: {DTM_URL}" in rendered
    assert "Fn::GetAtt" in rendered  # PublicIp pulled via GetAtt


def test_instance_role_can_read_persistence_secrets_and_ssm() -> None:
    """EC2 instance role grants secrets + SSM read on the arcnode-ems-* prefix."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "secretsmanager:GetSecretValue" in rendered
    assert "secret:arcnode-ems-" in rendered
    assert "ssm:GetParameter" in rendered
    assert "parameter/arcnode-ems/" in rendered


def test_render_template_includes_aurora_cluster() -> None:
    """Aurora resources merged into the template (both variants)."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraCluster" in rendered
    assert "AWS::RDS::DBCluster" in rendered
    assert "Custom::AuroraBootstrap" in rendered


def test_ec2_instance_depends_on_aurora_bootstrap() -> None:
    """EC2 must wait for the Aurora bootstrap Lambda before launching."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraBootstrapCustomResource" in rendered
    assert "DependsOn" in rendered


def test_commercial_template_declares_two_vendor_url_parameters() -> None:
    """Commercial variant: 2 NoEcho String params + 2 CFN-native vendor secrets."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "TimeseriesConnectionUrl:" in rendered
    assert "GraphConnectionUrl:" in rendered
    assert "TimeseriesUrlSecret:" in rendered
    assert "GraphUrlSecret:" in rendered
    # Commercial omits Neptune + AOSS
    assert "AWS::Neptune::DBCluster" not in rendered
    assert "AWS::OpenSearchServerless::Collection" not in rendered


def test_defense_template_includes_neptune_and_aoss_resources() -> None:
    """Defense variant: Neptune cluster + AOSS collection, no vendor params."""
    # Arrange + Act
    rendered = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert "AWS::Neptune::DBCluster" in rendered
    assert "AWS::OpenSearchServerless::Collection" in rendered
    # Defense has no vendor params
    assert "TimeseriesConnectionUrl:" not in rendered
    assert "GraphConnectionUrl:" not in rendered


def test_sovereign_government_routes_to_defense_variant() -> None:
    """SOVEREIGN_GOVERNMENT shares the defense template (Neptune + AOSS)."""
    # Arrange + Act
    rendered = _render(DeploymentContext.SOVEREIGN_GOVERNMENT)

    # Assert
    assert "AWS::Neptune::DBCluster" in rendered
    assert "AWS::OpenSearchServerless::Collection" in rendered


def test_commercial_userdata_writes_graph_url_into_secrets_env() -> None:
    """Commercial UserData reads graph-url Secret + writes GRAPH_URL into secrets.env."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert — fetches the Aura connection URL by Secrets Manager slot name
    assert "arcnode-ems-${AWS::StackName}/graph-url" in rendered
    # Assert — surfaces it in secrets.env under the GRAPH_URL env var
    assert "GRAPH_URL=" in rendered
    assert "/opt/arcnode/secrets.env" in rendered
    # Commercial doesn't fetch defense-only SSM params
    assert "neptune-host" not in rendered
    assert "aoss-host" not in rendered


def test_defense_userdata_writes_neptune_graph_block_into_analyst_cfg() -> None:
    """Defense UserData reads 3 SSM params + appends a neptune graph block
    to analyst-cfg.customer.yml so python-mcp-server picks NeptuneGraph."""
    # Arrange + Act
    rendered = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert — SSM lookups still happen
    assert "/arcnode-ems/${AWS::StackName}/neptune-host" in rendered
    assert "/arcnode-ems/${AWS::StackName}/aoss-host" in rendered
    assert "/arcnode-ems/${AWS::StackName}/neptune-loader-role-arn" in rendered
    # Assert — values flow into the analyst customer cfg under a graph block
    assert "backend: neptune" in rendered
    assert "neptune_host: $NEPTUNE_HOST" in rendered
    assert "aoss_host: $AOSS_HOST" in rendered
    assert "loader_role_arn: $NEPTUNE_LOADER_ROLE_ARN" in rendered
    assert ">> /opt/arcnode/analyst-cfg.customer.yml" in rendered
    # Defense doesn't fetch a graph-url secret (Neptune is IAM-auth)
    assert "/graph-url" not in rendered


def test_userdata_keeps_secrets_and_config_in_separate_env_files() -> None:
    """Credentials live in secrets.env; non-secret config lives in config.env.

    Avoids the conflation bug class — operators can see at the file level
    which values are sensitive without opening the values themselves.
    """
    # Arrange + Act
    commercial = _render(DeploymentContext.COMMERCIAL)
    defense = _render(DeploymentContext.DEFENSE_FORWARD)

    for rendered in (commercial, defense):
        # Assert — URL-bearing slots route to secrets.env
        assert "DOCUMENT_URL=" in rendered
        assert "VECTOR_URL=" in rendered
        assert "TIMESERIES_URL=" in rendered
        assert "DER_CONTROL_URL=" in rendered
        # The aws secretsmanager get-secret-value lines all append to secrets.env
        secret_section = rendered.split("/opt/arcnode/secrets.env")[1:]
        secret_block = "\n".join(secret_section)
        assert "secretsmanager get-secret-value" in secret_block
        # And no SSM get-parameter writes leak into secrets.env
        assert "ssm get-parameter" not in secret_block


def test_userdata_fetches_arcnode_public_static_artifacts() -> None:
    """UserData curls compose + init scripts from arcnode-public."""
    # Arrange + Act
    commercial = _render(DeploymentContext.COMMERCIAL)
    defense = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert — variant-specific compose URL
    assert "arcnode-public.s3" in commercial
    assert "/compose/commercial/docker-compose.yaml" in commercial
    assert "/compose/defense/docker-compose.yaml" in defense
    # Assert — the telemetry writer is an image with its script baked in; nothing to fetch.
    assert "/init-scripts/telemetry_writer.py" not in commercial
    assert "/init-scripts/telemetry_writer.py" not in defense
    assert "mkdir -p /opt/arcnode/init-scripts" not in commercial
    assert "mkdir -p /opt/arcnode/init-scripts" not in defense


def test_userdata_does_not_emit_arcnode_variant_flag() -> None:
    """No ARCNODE_VARIANT env — the per-variant compose file already
    encodes the deployment shape, and python-mcp-server dispatches off
    cfg.graph.backend. A separate flag would be a redundant signal.
    """
    # Arrange + Act
    commercial = _render(DeploymentContext.COMMERCIAL)
    defense = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert — no ARCNODE_VARIANT export in either variant's UserData
    assert "ARCNODE_VARIANT" not in commercial
    assert "ARCNODE_VARIANT" not in defense


def test_auth_secrets_and_params_in_both_variants() -> None:
    """Broker + device-api auth secrets are variant-agnostic (File RBAC runs in
    every deployment), so both commercial and defense render every secret
    plus the customer-set params behind them."""
    # Arrange + Act
    for ctx in (DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD):
        rendered = _render(ctx)

        # Assert — one secret per customer-set param
        for logical in (
            "MqttServicePwSecret",
            "AuthJwtSecretSecret",
            "AuthOperatorPwSecret",
            "AuthViewerPwSecret",
            "GrafanaAdminPwSecret",
        ):
            assert logical in rendered, f"{logical} missing in {ctx}"
        # NoEcho params the customer pastes
        assert "MqttServicePw" in rendered
        assert "AuthOperatorPw" in rendered
        assert "AuthViewerPw" in rendered
        assert "GrafanaAdminPw" in rendered


def test_userdata_writes_broker_credentials_xml() -> None:
    """UserData fetches the shared credentials template and fills its six
    password placeholders, writing /opt/arcnode/credentials.xml (bind-mounted
    into the File RBAC extension)."""
    # Arrange + Act
    rendered = _render()

    # Assert — the template comes from arcnode-public, the file lands where
    # compose mounts it, and every placeholder gets its password
    assert "/compose/credentials.template.xml" in rendered
    assert "/opt/arcnode/credentials.xml" in rendered
    for account in (
        "'GATEWAY', 'SVC_PW'",
        "'OPERATOR', 'OP_PW'",
        "'VIEWER', 'VW_PW'",
        "'DEVICE_API', 'SVC_PW'",
        "'TELEMETRY_WRITER', 'SVC_PW'",
        "'DER_CONTROL_API', 'SVC_PW'",
    ):
        assert account in rendered, f"{account} not filled"
    assert "MQTT_DER_CONTROL_API_PASSWORD" in rendered
    # Reason: the four service accounts share one customer-set secret, fetched once.
    assert "arcnode-ems-${AWS::StackName}/mqtt-service-password" in rendered
    assert "mqtt-gateway-password" not in rendered


def test_userdata_fetches_auth_slots_into_secrets_env() -> None:
    """The six auth env vars land in secrets.env so device-api + gateway can
    read them (names must match what those services consume)."""
    # Arrange + Act
    rendered = _render()

    # Assert
    for env in (
        "MQTT_GATEWAY_PASSWORD",
        "MQTT_OPERATOR_PASSWORD",
        "MQTT_VIEWER_PASSWORD",
        "MQTT_DER_CONTROL_API_PASSWORD",
        "AUTH_JWT_SECRET",
        "AUTH_OPERATOR_PW",
        "AUTH_VIEWER_PW",
    ):
        assert env in rendered, f"{env} not fetched into secrets.env"


def test_userdata_writes_hmi_runtime_config() -> None:
    """UserData writes hmi-cfg.customer.yml with same-origin relative URIs +
    empty mqttUri (SPA derives the broker URL) + the site id. Served by the
    HMI container's nginx and fetched by the static SPA at boot."""
    # Arrange + Act
    rendered = _render()

    # Assert — file + the runtime-config fields the SPA needs
    assert "/opt/arcnode/hmi-cfg.customer.yml" in rendered
    # split("YML")[1] = body between the `<<YML` opener and its `YML` close.
    hmi_block = rendered.split("hmi-cfg.customer.yml")[1].split("YML")[1]
    assert f"siteId: {SITE_ID}" in hmi_block
    assert "deviceApiUri: /api" in hmi_block
    # chatApiUri empty → nginx passes /analyst/chat through un-stripped.
    assert "chatApiUri:" in hmi_block
    # empty string → SPA derives the broker URL. The "" is YAML-escaped in
    # the template scalar; cloud-init decodes it back to mqttUri: "" on disk.
    assert "mqttUri:" in hmi_block


def test_security_group_opens_der_control_mtls_port() -> None:
    """8443 is open for der-control-ingress — the mTLS handshake itself is
    the gate, so opening the port to the world is fine (matches the 8000
    analyst-server precedent: no auth at the SG layer for either)."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "FromPort: 8443" in rendered
    assert "ToPort: 8443" in rendered


def test_der_control_truststore_secret_provisioned_both_variants() -> None:
    """A placeholder Secrets Manager slot for der-control-ingress's mTLS
    truststore — ops overwrites it with the real per-DERMS-integration CA
    bundle post-deploy (not wired into customer order intake; that's a
    separate, bigger decision)."""
    # Arrange + Act
    for ctx in (DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD):
        rendered = _render(ctx)

        # Assert
        assert "DerControlTruststoreSecret" in rendered, f"missing in {ctx}"
        assert "der-control-truststore-pem" in rendered, f"missing in {ctx}"


def test_userdata_writes_der_control_ingress_tls_assets() -> None:
    """UserData: self-signed server cert/key for der-control-ingress, the
    ops-populated truststore fetched from Secrets Manager, and the static
    nginx mTLS config — all the files der-control-ingress bind-mounts."""
    # Arrange + Act
    rendered = _render()

    # Assert — self-signed cert/key generated at boot (mirrors the ISO
    # appliance's own TLS role — same openssl one-liner shape)
    assert "/opt/arcnode/der-control-tls/cert.pem" in rendered
    assert "/opt/arcnode/der-control-tls/key.pem" in rendered
    assert "openssl req -x509" in rendered
    # Assert — truststore fetched from the placeholder secret, not secrets.env
    # (it's a PEM bundle, not a KEY=VALUE line)
    assert "der-control-truststore-pem" in rendered
    assert "/opt/arcnode/der-control-truststore.pem" in rendered
    # Assert — static nginx config fetched from arcnode-public, same pattern
    # as the observability configs
    assert f"{ARCNODE_PUBLIC_BASE_URL}/der-control-ingress/nginx.conf" in rendered
    assert "/opt/arcnode/der-control-ingress.conf" in rendered


def test_stack_exposes_gateway_bootstrap_contract() -> None:
    """The on-prem gateway container self-configures from the stack: it reads
    these outputs (+ the gateway secret) with the customer's AWS creds. EIP so
    the address survives instance stop/start."""
    # Arrange + Act
    rendered = _render()

    # Assert — stable address
    assert "AWS::EC2::EIP" in rendered
    # Assert — the outputs the bootstrap reads
    for out in ("SiteId", "BrokerWsUrl", "DeviceApiUrl", "GatewaySecretName"):
        assert out in rendered, f"missing output {out}"
    assert "wss://${EmsEip}/mqtt" in rendered
    assert "https://${EmsEip}/api" in rendered
    assert f"SiteId:\n    Value: {SITE_ID}" in rendered or SITE_ID in rendered


def test_commercial_userdata_writes_analyst_model_cfg_with_mlflow_address() -> None:
    """Commercial UserData writes analyst-model-cfg.customer.yml pointing the
    model at the compose-network MLflow, not the dev box in cfg.yml."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert — written by the same heredoc pattern as the other overlays
    assert "cat > /opt/arcnode/analyst-model-cfg.customer.yml <<YML" in rendered
    model_block = rendered.split("analyst-model-cfg.customer.yml <<YML")[1]
    heredoc_body = model_block.split("YML\n")[0]
    assert "mlflow_tracking_uri: http://mlflow:5000" in heredoc_body
    assert "site_id:" in heredoc_body


def test_userdata_writes_lfdi_allowlist_on_one_line() -> None:
    """The LFDI allowlist is written into secrets.env as one line, newlines
    turned into spaces, so der-control-api reads it at boot. An empty or
    placeholder value fails closed."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "arcnode-ems-${AWS::StackName}/der-control-lfdi-allowlist" in rendered
    assert "DER_CONTROL_LFDI_ALLOWLIST=$(" in rendered
    assert "--output text | tr " in rendered


def test_userdata_hmi_overlay_has_der_control_uri() -> None:
    """The HMI refuses to boot without derControlUri in its overlay. It routes
    same-origin through the HMI's nginx to der-control-api's events read."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "derControlUri:" in rendered
    assert "/der-control" in rendered


def test_commercial_userdata_writes_der_control_cfg() -> None:
    """Cloud UserData writes der-control-api's per-site keys: the order's siteId,
    and publicBaseUrl at the ingress on the stack's Elastic IP. No DERMS URL yet."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "cat > /opt/arcnode/der-control-cfg.customer.yml <<YML" in rendered
    block = rendered.split("der-control-cfg.customer.yml <<YML")[1].split("YML\n")[0]
    assert "publicBaseUrl: https://${EmsEip}:8443" in block
    assert "siteId:" in block
    assert "utilityMirrorUrl" not in block


def test_cloud_instance_is_m7i_2xlarge() -> None:
    """Cloud runs the container stack on CPU only; LLMs are Bedrock on demand.
    8 vCPU matches the on-prem spec; no GPU needed."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "InstanceType: m7i.2xlarge" in rendered


def test_cloud_instance_uses_the_stock_al2023_ami_for_every_variant() -> None:
    """Every cloud variant boots the stock Amazon Linux 2023 AMI, GovCloud included,
    so there is no custom image to build or copy."""
    # Arrange + Act
    commercial = _render(DeploymentContext.COMMERCIAL)
    defense = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert
    stock = "resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
    assert stock in commercial
    assert stock in defense
    assert "base-ami-id" not in commercial


@pytest.mark.parametrize(
    "context", [DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD]
)
def test_userdata_starts_the_containers_once_secrets_env_is_written(
    context: DeploymentContext,
) -> None:
    """The stack's parameters carry every customer input, so the box starts the EMS at boot."""
    # Arrange + Act
    rendered = _render(context)

    # Assert
    assert rendered.index(": > /opt/arcnode/secrets.env") < rendered.index(
        "docker compose -f docker-compose.yaml up -d"
    )


def test_hmi_overlay_routes_chat_through_the_same_origin_api() -> None:
    """The HMI composes ${chatApiUri}/analyst/chat, and nginx serves the analyst under /api."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "chatApiUri:" in rendered
    assert "/api" in rendered


def test_userdata_prepares_the_https_ingress_with_a_self_signed_cert_for_the_eip() -> (
    None
):
    """Port 443 serves the HMI from first boot: the static ingress config is fetched
    and a self-signed cert for the Elastic IP is written where the ingress mounts it."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert f"{ARCNODE_PUBLIC_BASE_URL}/compose/https-ingress.conf" in rendered
    assert "-o /opt/arcnode/https-ingress.conf" in rendered
    assert "-out /opt/arcnode/tls/server.pem" in rendered
    assert "-keyout /opt/arcnode/tls/server-key.pem" in rendered
    assert "subjectAltName=IP:${EmsEip}" in rendered


def test_userdata_hands_the_observability_data_dirs_to_the_containers_users() -> None:
    """Prometheus (uid 65534) and Grafana (uid 472) don't run as root, so a root-owned
    data dir crash-loops them with 'permission denied'."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert — created, then chowned, before compose ever starts
    assert "chown -R 65534:65534 /opt/arcnode/observability/prometheus-data" in rendered
    assert "chown -R 472:472 /opt/arcnode/observability/grafana-data" in rendered
    assert rendered.index("chown -R 472:472") < rendered.index("docker compose")


def test_the_instance_firewall_opens_https_for_the_ingress() -> None:
    """Port 80 redirects to HTTPS, the ingress listens on 443, and 8443 is the DER control
    mTLS intake. Nothing else is open."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)
    template = yaml.safe_load(rendered)
    ingress = template["Resources"]["EmsSecurityGroup"]["Properties"][
        "SecurityGroupIngress"
    ]

    # Assert
    assert sorted(rule["FromPort"] for rule in ingress) == [80, 443, 8443]
    assert all(rule["CidrIp"] == "0.0.0.0/0" for rule in ingress)


CALLBACK = SiteCallback(
    url="https://platform.arcnode.io/platform-api/sites/abc/address",
    token="tok-123",
    hostname="nevada-facility-2-abc123.arcnode.io",
)


def test_userdata_registers_the_box_and_gets_a_real_certificate_in_the_background() -> (
    None
):
    """With a callback the box tells platform-api its Elastic IP, waits for its DNS name to
    resolve, and gets a Let's Encrypt certificate: all from a background service, so a slow DNS
    or ACME step never holds the stack's CreationPolicy."""
    # Arrange + Act
    rendered = _render(site_callback=CALLBACK)

    # Assert — its settings, its script, and the service that runs it
    assert "SITE_HOST=nevada-facility-2-abc123.arcnode.io" in rendered
    assert "SITE_ADDRESS=${EmsEip}" in rendered
    assert (
        "SITE_CALLBACK_URL=https://platform.arcnode.io/platform-api/sites/abc/address"
        in rendered
    )
    assert "SITE_TOKEN=tok-123" in rendered
    assert f"{ARCNODE_PUBLIC_BASE_URL}/compose/site-cert.sh" in rendered
    assert "arcnode-site-cert.service" in rendered
    assert "systemctl enable --now arcnode-site-cert" in rendered
    assert "chmod 600 /etc/arcnode/site-cert.env" in rendered


def test_without_a_callback_the_stack_keeps_the_self_signed_certificate_only() -> None:
    """e2e stacks and local renders have no zone to write: no callback, no cert service."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "site-cert" not in rendered
    assert "SITE_TOKEN" not in rendered


def test_the_outputs_point_at_the_dns_name_when_there_is_one() -> None:
    # Arrange + Act
    outputs = yaml.safe_load(_render(site_callback=CALLBACK))["Outputs"]

    # Assert
    assert (
        outputs["BrokerWsUrl"]["Value"]
        == "wss://nevada-facility-2-abc123.arcnode.io/mqtt"
    )
    assert (
        outputs["DeviceApiUrl"]["Value"]
        == "https://nevada-facility-2-abc123.arcnode.io/api"
    )


def test_the_outputs_fall_back_to_the_elastic_ip_over_tls_without_one() -> None:
    # Arrange + Act
    outputs = yaml.safe_load(_render())["Outputs"]

    # Assert
    assert outputs["BrokerWsUrl"]["Value"] == {"Fn::Sub": "wss://${EmsEip}/mqtt"}
    assert outputs["DeviceApiUrl"]["Value"] == {"Fn::Sub": "https://${EmsEip}/api"}


@pytest.mark.parametrize(
    "context", [DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD]
)
def test_the_customer_picks_the_telemetry_window(context: DeploymentContext) -> None:
    """TelemetryRetentionDays defaults to 7 and lands in telemetry-writer's overlay."""
    # Arrange + Act
    rendered = _render(context)
    template = yaml.safe_load(rendered)

    # Assert
    param = template["Parameters"]["TelemetryRetentionDays"]
    assert (param["Type"], param["Default"], param["MinValue"]) == ("Number", 7, 1)
    assert "cat > /opt/arcnode/telemetry-writer-cfg.customer.yml" in rendered
    assert "retention_days: ${TelemetryRetentionDays}" in rendered
