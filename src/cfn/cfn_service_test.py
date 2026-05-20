"""Unit tests for `CfnService.render_template`.

Validates the rendered yaml against the CloudFormation spec via cfn-lint
(AST + spec check, no AWS creds) and asserts the structural shape we
need: VPC + IAM + EC2 + UserData that boots docker-compose with the EMS
core triplet (device-api + hmi + industrial-gateway) wired to the three
managed-service connection strings the operator must supply.

Server-side validation (live image pulls, IAM evaluation, real launch)
happens when the operator actually runs the stack — out of scope here.
"""

from cfnlint import api as cfnlint_api

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext

DEPLOYMENT_UUID: str = "abcd1234-5678-90ef-1234-567890abcdef"
DTM_URL: str = "https://platform-api-artifacts.example/orders/o1/dtm.json"
SITE_ID: str = "test_site"


def _render(
    deployment_context: DeploymentContext = DeploymentContext.COMMERCIAL,
    *,
    e2e: bool = False,
) -> str:
    return CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=DEPLOYMENT_UUID,
        dtm_url=DTM_URL,
        site_id=SITE_ID,
        wholesale_market="ercot",
        settlement_point="HB_NORTH",
        deployment_context=deployment_context,
        e2e=e2e,
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
    # SSM resolve syntax — CFN looks up the latest AL2023 AMI in --region
    assert "resolve:ssm:/aws/service/ami-amazon-linux-latest" in rendered
    # No stale Mappings table
    assert "Mappings:" not in rendered


def test_render_template_userdata_installs_docker_and_starts_compose() -> None:
    """UserData bootstraps docker + compose, fetches artifacts, runs the stack."""
    # Arrange + Act
    rendered = _render()

    # Assert — bash shell + the expected file layout
    assert "#!/bin/bash" in rendered
    assert "/opt/arcnode/config.env" in rendered
    assert "/opt/arcnode/secrets.env" in rendered
    assert "/opt/arcnode/userdata.done" in rendered
    assert DTM_URL in rendered
    # Assert — docker install + compose up wire the EMS stack onto the EC2
    assert "dnf install -y docker" in rendered
    assert "systemctl enable --now docker" in rendered
    assert "docker compose up -d" in rendered
    # No reference to the old private registry — images come from ECR Public
    assert "registry.gitlab.com" not in rendered


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
    # Trap fires cfn-signal -e 1 on ANY error
    assert "trap '/usr/bin/cfn-signal -e 1" in rendered
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
    # Assert — telemetry-writer init script common to both. All seed
    # init scripts (vector/graph/ercot) moved to consumer-self-seed.
    assert "/init-scripts/telemetry_writer.py" in commercial
    assert "/init-scripts/telemetry_writer.py" in defense


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
