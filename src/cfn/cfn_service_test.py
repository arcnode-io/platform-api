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
EMS_MODE: str = "sim"


def _render(
    deployment_context: DeploymentContext = DeploymentContext.COMMERCIAL,
) -> str:
    return CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=DEPLOYMENT_UUID,
        dtm_url=DTM_URL,
        ems_mode=EMS_MODE,
        deployment_context=deployment_context,
    )


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


def test_render_template_provisions_instance_role_for_dtm_fetch() -> None:
    """An IAM role + InstanceProfile so the EC2 can s3:GetObject the DTM."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AWS::IAM::Role" in rendered
    assert "AWS::IAM::InstanceProfile" in rendered
    assert "s3:GetObject" in rendered


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


def test_render_template_userdata_drops_marker_files() -> None:
    """Pre-launch UserData touches /opt/arcnode/ marker files (no docker yet).

    Persistence connection-string fetch lands in Task 14 (Secrets Manager
    + AWS CLI). For now UserData only writes deployment env + DTM fetch.
    """
    # Arrange + Act
    rendered = _render()

    # Assert — bash shell + dummy-file scaffolding
    assert "#!/bin/bash" in rendered
    assert "/opt/arcnode/deployment.env" in rendered
    assert "/opt/arcnode/userdata.done" in rendered
    assert DTM_URL in rendered  # curl line bakes the DTM URL in directly
    # No docker bits — those land when registry images are published
    assert "docker compose" not in rendered
    assert "registry.gitlab.com" not in rendered


def test_render_template_outputs_echo_per_order_inputs() -> None:
    """Outputs include the public IP + the order's params for op visibility."""
    # Arrange + Act
    rendered = _render()

    # Assert — `safe_dump(sort_keys=False)` produces stable `Value:` lines
    assert f"Value: {DEPLOYMENT_UUID}" in rendered
    assert f"Value: {DTM_URL}" in rendered
    assert f"Value: {EMS_MODE}" in rendered
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


def test_commercial_userdata_fetches_graph_secret_from_secrets_manager() -> None:
    """Commercial UserData fetches graph-url from Secrets Manager (Aura URL has creds)."""
    # Arrange + Act
    rendered = _render(DeploymentContext.COMMERCIAL)

    # Assert
    assert "arcnode-ems-${AWS::StackName}/graph-url" in rendered
    # Commercial doesn't need neptune-host or aoss-host
    assert "neptune-host" not in rendered
    assert "aoss-host" not in rendered


def test_defense_userdata_fetches_neptune_and_aoss_from_ssm() -> None:
    """Defense UserData reads neptune-host + aoss-host from SSM Parameter Store."""
    # Arrange + Act
    rendered = _render(DeploymentContext.DEFENSE_FORWARD)

    # Assert
    assert "/arcnode-ems/${AWS::StackName}/neptune-host" in rendered
    assert "/arcnode-ems/${AWS::StackName}/aoss-host" in rendered
    # Defense doesn't fetch a graph-url secret (Neptune is IAM-auth)
    assert "/graph-url" not in rendered
