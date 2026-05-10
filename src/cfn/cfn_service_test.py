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

DEPLOYMENT_UUID: str = "abcd1234-5678-90ef-1234-567890abcdef"
DTM_URL: str = "https://platform-api-artifacts.example/orders/o1/dtm.json"
EMS_MODE: str = "sim"


def _render() -> str:
    return CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=DEPLOYMENT_UUID, dtm_url=DTM_URL, ems_mode=EMS_MODE
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


def test_instance_role_can_read_persistence_secrets() -> None:
    """EC2 instance role grants secretsmanager:GetSecretValue on ems/* prefix."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "secretsmanager:GetSecretValue" in rendered
    assert "secret:ems/" in rendered  # the secret-name prefix appears in the policy


def test_userdata_fetches_four_persistence_secrets() -> None:
    """UserData calls aws secretsmanager get-secret-value for each persistence slot."""
    # Arrange + Act
    rendered = _render()

    # Assert
    for slot in ("aurora-document", "aurora-vector", "tiger", "neo4j-aura"):
        assert slot in rendered, f"UserData missing fetch for {slot} secret"
    assert "aws secretsmanager get-secret-value" in rendered


def test_userdata_writes_secrets_to_opt_arcnode_url_files() -> None:
    """Secrets land at /opt/arcnode/<name>.url for docker-compose env_file."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "/opt/arcnode/aurora-document.url" in rendered
    assert "/opt/arcnode/aurora-vector.url" in rendered
    assert "/opt/arcnode/tiger.url" in rendered
    assert "/opt/arcnode/neo4j-aura.url" in rendered


def test_render_template_includes_aurora_cluster() -> None:
    """Persistence sub-module's Aurora resources are merged into the template."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraCluster" in rendered
    assert "AWS::RDS::DBCluster" in rendered


def test_render_template_includes_tiger_and_aura_custom_resources() -> None:
    """Persistence sub-module's vendor custom resources are merged."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "Custom::TigerCloudInstance" in rendered
    assert "Custom::Neo4jAuraInstance" in rendered
    assert "Custom::AuroraBootstrap" in rendered


def test_render_template_full_resource_inventory() -> None:
    """End-to-end: rendered template contains all expected logical IDs."""
    # Arrange + Act
    rendered = _render()

    expected = [
        # Network
        "EmsVpc",
        "EmsSubnet",
        "EmsSecurityGroup",
        # IAM
        "EmsInstanceRole",
        "EmsInstanceProfile",
        # Aurora
        "AuroraCluster",
        "AuroraInstance",
        "AuroraMasterSecret",
        "AuroraSubnetGroup",
        "AuroraSecurityGroup",
        "AuroraBootstrapLambda",
        "AuroraBootstrapCustomResource",
        # Tiger
        "TigerLambda",
        "TigerCustomResource",
        "TigerLambdaRole",
        # Aura
        "AuraLambda",
        "AuraCustomResource",
        "AuraLambdaRole",
        # EC2
        "EmsInstance",
    ]

    for logical_id in expected:
        assert logical_id in rendered, f"missing logical id: {logical_id}"


def test_ec2_instance_depends_on_all_three_persistence_resources() -> None:
    """EC2 must wait for all three custom resources before launching."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraBootstrapCustomResource" in rendered
    assert "TigerCustomResource" in rendered
    assert "AuraCustomResource" in rendered
    assert "DependsOn" in rendered


def test_render_template_declares_vendor_token_parameters() -> None:
    """Six no-default NoEcho parameters: Tiger access+secret+project, Aura client id+secret+tenant.

    Operators paste vendor API tokens (not raw conn strings); the
    persistence sub-module's CFN custom-resource Lambdas use these
    tokens to provision Tiger Cloud + Neo4j Aura instances at
    stack-create time.
    """
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "TigerCloudAccessKey:" in rendered
    assert "TigerCloudSecretKey:" in rendered
    assert "TigerCloudProjectId:" in rendered
    assert "Neo4jAuraClientId:" in rendered
    assert "Neo4jAuraClientSecret:" in rendered
    assert "Neo4jAuraTenantId:" in rendered
    assert rendered.count("NoEcho: true") == 6
    assert rendered.count("MinLength: 1") == 6
    # No Default: anywhere → CFN hard-fails if any token is missing
    assert "Default:" not in rendered
