"""Unit tests for the header badge — one label per deployment: On-Prem,
Commercial, or Defense. The badge comes from the box's deployment and variant."""

from src.wizard.wizard_record import Badge, Deployment, Variant, badge_for


def test_on_prem_box_is_labelled_on_prem() -> None:
    # Arrange + Act
    badge = badge_for(Deployment.ON_PREM, Variant.COMMERCIAL)

    # Assert
    assert badge == Badge.ON_PREM
    assert badge.value == "On-Prem"


def test_commercial_cloud_box_is_labelled_commercial() -> None:
    # Arrange + Act
    badge = badge_for(Deployment.CLOUD, Variant.COMMERCIAL)

    # Assert
    assert badge == Badge.COMMERCIAL


def test_defense_cloud_box_is_labelled_defense() -> None:
    # Arrange + Act
    badge = badge_for(Deployment.CLOUD, Variant.DEFENSE)

    # Assert
    assert badge == Badge.DEFENSE
