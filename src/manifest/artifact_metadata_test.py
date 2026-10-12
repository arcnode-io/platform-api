"""The shipped artifact table never shows a placeholder count to a customer."""

from src.edp_client.edp_artifacts import ArtifactKind
from src.manifest.artifact_metadata import (
    MOCK_ARTIFACT_METADATA,
    MOCK_SYSTEM_IMAGE_TEMPLATES,
)


def test_no_shipped_subtitle_carries_a_placeholder_or_mock_label() -> None:
    # Arrange + Act
    subtitles = [m.subtitle for m in MOCK_ARTIFACT_METADATA.values() if m.subtitle]

    # Assert — no "MOCK" text; every count is labelled as an estimate
    assert not any("MOCK" in s for s in subtitles)
    for s in subtitles:
        if any(c.isdigit() for c in s):
            assert s.startswith("Estimated · "), s


def test_the_counted_artifacts_are_labelled_estimates_until_edp_api_emits_counts() -> (
    None
):
    # Arrange + Act + Assert
    for key in (ArtifactKind.BOM, ArtifactKind.CABLE_HOSE_SCHEDULE, ArtifactKind.DTM):
        subtitle = MOCK_ARTIFACT_METADATA[key].subtitle
        assert subtitle is not None and subtitle.startswith("Estimated · ")
    assert MOCK_ARTIFACT_METADATA[ArtifactKind.INTERFACE_PLATE].subtitle is None


def test_the_android_row_describes_only_the_apk_with_its_real_minimum_sdk() -> None:
    """Minimum SDK is from the shipped APK (aapt: sdkVersion 24). Only the APK format is named."""
    # Arrange + Act
    subtitle = MOCK_SYSTEM_IMAGE_TEMPLATES["ems_field_client"].subtitle

    # Assert
    assert subtitle == "Android 7.0+ · APK"
