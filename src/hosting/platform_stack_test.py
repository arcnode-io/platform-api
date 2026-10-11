"""The platform.arcnode.io stack: lint-clean, stock AL2023, containers can reach IMDS."""

from pathlib import Path

import yaml
from cfnlint import api as cfnlint_api

TEMPLATE: Path = Path(__file__).parent / "platform-stack.yaml"


def test_platform_stack_passes_cfn_lint() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Act
    matches = cfnlint_api.lint(template)

    # Assert
    assert matches == []


def test_platform_stack_boots_stock_al2023_and_lets_containers_use_the_role() -> None:
    # Arrange
    template = _load_cfn(TEMPLATE.read_text())

    # Act
    instance = template["Resources"]["Instance"]["Properties"]
    image_default = template["Parameters"]["ImageId"]["Default"]

    # Assert
    assert (
        image_default
        == "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
    )
    assert instance["MetadataOptions"] == {
        "HttpTokens": "required",
        "HttpPutResponseHopLimit": 2,
    }
    assert instance["Tags"] == [{"Key": "Name", "Value": "arcnode-platform"}]


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that accepts CFN's !Ref/!Sub/!GetAtt tags as plain values."""


for tag in ("!Ref", "!Sub", "!GetAtt"):
    _CfnLoader.add_constructor(tag, lambda loader, node: loader.construct_scalar(node))


def _load_cfn(text: str) -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    """yaml.safe_load, but through the CFN-aware SafeLoader subclass."""
    loader = _CfnLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
