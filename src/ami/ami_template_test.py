"""The base AMI template: Amazon Linux 2023 with Docker and the setup wizard
baked in, so a cloud box boots with everything the on-prem ISO carries."""

from pathlib import Path

TEMPLATE: Path = Path(__file__).parent / "ems-base.pkr.hcl"


def test_builds_from_amazon_linux_2023_with_a_50_gb_root() -> None:
    # Arrange
    text = TEMPLATE.read_text()

    # Assert — the same base the stack uses today, same root size as the stack's volume
    assert 'source "amazon-ebs" "ems"' in text
    assert "al2023-ami-2023" in text
    assert "volume_size           = 50" in text


def test_bakes_the_wizard_into_the_image() -> None:
    # Arrange
    text = TEMPLATE.read_text()

    # Assert — the wizard source comes from this repo, not the network at boot
    assert 'source      = "src/wizard/"' in text
    assert "/opt/arcnode-wizard-src/src/wizard" in text


def test_names_the_ami_by_release_so_each_build_is_findable() -> None:
    # Arrange
    text = TEMPLATE.read_text()

    # Assert
    assert "ami_name" in text
    assert "arcnode-ems-base-" in text


def test_writes_a_manifest_so_ci_can_read_the_new_ami_id() -> None:
    # Arrange
    text = TEMPLATE.read_text()

    # Assert
    assert 'post-processor "manifest"' in text


def test_installs_the_wizard_python_dependencies_into_the_image() -> None:
    """The wizard runs on the box with the same libraries the ISO installs."""
    # Arrange
    text = TEMPLATE.read_text()

    # Assert
    assert "/opt/arcnode-wizard-venv/bin/pip install" in text
    assert "fastapi" in text
    assert "uvicorn" in text
    assert "pydantic" in text
    assert "pyyaml" in text
