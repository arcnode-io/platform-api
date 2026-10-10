"""Unit tests for filling the broker's credentials.xml template on-prem."""

# Reason: the test parses the XML we rendered ourselves, not untrusted input.
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path

from src.wizard.hivemq_credentials import render_credentials

TEMPLATE: Path = Path(__file__).parents[1] / "compose" / "credentials.template.xml"


def test_render_escapes_xml_characters_in_passwords() -> None:
    # Arrange
    passwords = {
        "GATEWAY_PASSWORD": "a&b<c>\"d'e",
        "OPERATOR_PASSWORD": "op",
        "VIEWER_PASSWORD": "vw",
        "DEVICE_API_PASSWORD": "da",
        "TELEMETRY_WRITER_PASSWORD": "tw",
        "DER_CONTROL_API_PASSWORD": "dca",
    }

    # Act
    rendered = render_credentials(TEMPLATE.read_text(), passwords)

    # Assert
    # Reason: parsing our own rendered template, not untrusted input.
    root = ET.fromstring(rendered)  # noqa: S314  # nosec B314
    gateway = root.find("users/user[name='arcnode_gateway']/password")
    assert gateway is not None
    assert gateway.text == "a&b<c>\"d'e"
