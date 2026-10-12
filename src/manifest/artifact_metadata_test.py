"""The shipped artifact table carries no invented numbers and no MOCK text."""

from src.edp_client.edp_artifacts import ArtifactKind
from src.manifest.artifact_metadata import (
    MOCK_ARTIFACT_METADATA,
    MOCK_SYSTEM_IMAGE_TEMPLATES,
)


def test_no_shipped_subtitle_carries_a_placeholder_or_mock_label() -> None:
    # Arrange
    tables = (MOCK_ARTIFACT_METADATA, MOCK_SYSTEM_IMAGE_TEMPLATES)
    subtitles = [m.subtitle for table in tables for m in table.values() if m.subtitle]

    # Act + Assert
    assert not any("MOCK" in s or "Estimated" in s for s in subtitles)


def test_the_counted_artifacts_take_their_subtitle_from_edp_api_not_the_table() -> None:
    # Arrange + Act + Assert
    for key in (
        ArtifactKind.BOM,
        ArtifactKind.CABLE_HOSE_SCHEDULE,
        ArtifactKind.DTM,
        ArtifactKind.INTERFACE_PLATE,
    ):
        assert MOCK_ARTIFACT_METADATA[key].subtitle is None


def test_the_android_row_describes_only_the_apk_with_its_real_minimum_sdk() -> None:
    """Minimum SDK is from the shipped APK (aapt: sdkVersion 24). Only the APK format is named."""
    # Arrange + Act
    subtitle = MOCK_SYSTEM_IMAGE_TEMPLATES["ems_field_client"].subtitle

    # Assert
    assert subtitle == "Android 7.0+ · APK"
