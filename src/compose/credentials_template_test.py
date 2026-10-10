"""The broker ACL the cloud and on-prem both fill — its topic grants are the
contract the EMS services depend on."""

from pathlib import Path

TEMPLATE: Path = Path(__file__).parent / "credentials.template.xml"


def test_gateway_may_subscribe_the_system_control_plane() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Act
    gateway_role = template.split('<role><id>gateway</id>')[1].split('</role>')[0]

    # Assert — the gateway hot-reloads topology off system/topology_changed; a
    # denied subscribe fails loud on the gateway, not here.
    assert "<topic>system/#</topic><activity>SUBSCRIBE</activity>" in gateway_role


def test_der_control_api_gets_its_dispatch_grants() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Assert — a denied SUBSCRIBE fails silently (SUBACK discarded), unlike a
    # denied PUBLISH, so these grants are easy to lose and never show up as errors.
    assert template.count("<topic>sites/+/devices/der_dispatch/measurements/#</topic>") >= 2
    assert "<topic>sites/+/devices/der_dispatch/commands/#</topic>" in template
    assert "<topic>sites/+/devices/operating_envelope/measurements/#</topic>" in template


def test_mock_derms_has_no_broker_identity() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Assert — mock_derms is a separate trust domain (ems/readme.md)
    assert "mock_derms" not in template


def test_dispatch_lifecycle_events_are_granted() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Assert — without these, dispatch acks are silently denied
    assert template.count("<topic>sites/+/devices/+/events/#</topic>") >= 3


def test_operator_and_viewer_may_subscribe_the_system_plane() -> None:
    # Arrange
    template = TEMPLATE.read_text()

    # Act
    operator_role = template.split('<role><id>operator</id>')[1].split('</role>')[0]
    viewer_role = template.split('<role><id>viewer</id>')[1].split('</role>')[0]

    # Assert — the HMI hears system/loto_changed and system/topology_changed; a
    # denied SUBSCRIBE fails silently (SUBACK discarded), so the test guards it.
    system_subscribe = "<topic>system/#</topic><activity>SUBSCRIBE</activity>"
    assert system_subscribe in operator_role
    assert system_subscribe in viewer_role
