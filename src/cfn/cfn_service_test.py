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

from src.cfn.cfn_resources import EMS_REGISTRY, EMS_SERVICES
from src.cfn.cfn_service import CfnService

DEPLOYMENT_UUID: str = "abcd1234-5678-90ef-1234-567890abcdef"
DTM_URL: str = "https://platform-api-artifacts.example/orders/o1/dtm.json"
EMS_MODE: str = "sim"


def _render() -> str:
    return CfnService().render_template(
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


def test_render_template_ec2_instance_wires_to_subnet_iam_and_ami_map() -> None:
    """EmsInstance refs the subnet, IAM profile, security group, and region→AMI map."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AWS::EC2::Instance" in rendered
    assert "EmsInstanceProfile" in rendered
    assert "EmsSubnet" in rendered
    assert "EmsSecurityGroup" in rendered
    assert "RegionAmi" in rendered  # Mappings entry the EC2 looks up


def test_render_template_userdata_pulls_each_ems_service_image() -> None:
    """UserData boots docker-compose pulling each EMS core service from GitLab CR."""
    # Arrange + Act
    rendered = _render()

    # Assert — each EMS service image is referenced
    for svc in EMS_SERVICES:
        assert f"{EMS_REGISTRY}/{svc}:latest" in rendered, svc
    assert "#!/bin/bash" in rendered
    assert "docker compose up -d" in rendered
    assert DTM_URL in rendered  # curl line bakes the DTM URL in directly


def test_render_template_outputs_echo_per_order_inputs() -> None:
    """Outputs include the public IP + the order's params for op visibility."""
    # Arrange + Act
    rendered = _render()

    # Assert — `safe_dump(sort_keys=False)` produces stable `Value:` lines
    assert f"Value: {DEPLOYMENT_UUID}" in rendered
    assert f"Value: {DTM_URL}" in rendered
    assert f"Value: {EMS_MODE}" in rendered
    assert "Fn::GetAtt" in rendered  # PublicIp pulled via GetAtt


def test_render_template_requires_three_persistence_connection_strings() -> None:
    """Three required no-default CFN parameters, NoEcho true, MinLength 1.

    PM contract: operator must paste Neon + Neo4j Aura + TimescaleDB connection
    strings at create-stack time. CFN hard-fails if any is missing because none
    have a Default.
    """
    # Arrange + Act
    rendered = _render()

    # Assert — each parameter named + sensitive-marked + non-empty constraint
    assert "NeonConnectionString:" in rendered
    assert "AuraConnectionString:" in rendered
    assert "TimeseriesConnectionString:" in rendered
    assert rendered.count("NoEcho: true") == 3
    assert rendered.count("MinLength: 1") == 3
    # No `Default:` lines anywhere = stack creation fails without all three
    assert "Default:" not in rendered


def test_render_template_userdata_substitutes_connection_strings_via_sub() -> None:
    """UserData uses Fn::Sub so the three params land as docker-compose env vars."""
    # Arrange + Act
    rendered = _render()

    # Assert — CFN does the substitution server-side
    assert "Fn::Sub" in rendered
    assert "${NeonConnectionString}" in rendered
    assert "${AuraConnectionString}" in rendered
    assert "${TimeseriesConnectionString}" in rendered


def test_render_template_each_ems_service_gets_all_three_db_envs() -> None:
    """All 3 EMS services receive all 3 connection strings as env vars."""
    # Arrange + Act
    rendered = _render()
    n = len(EMS_SERVICES)

    # Assert — once per service for each env var key
    assert rendered.count("NEON_DATABASE_URL:") == n
    assert rendered.count("AURA_URI:") == n
    assert rendered.count("TIMESERIES_URL:") == n
