"""The shipped artifact table never shows a placeholder count to a customer."""

from src.edp_client.edp_artifacts import ArtifactKind
from src.manifest.artifact_metadata import MOCK_ARTIFACT_METADATA


def test_no_shipped_subtitle_carries_a_placeholder_or_mock_label() -> None:
    # Arrange + Act
    subtitles = [m.subtitle for m in MOCK_ARTIFACT_METADATA.values() if m.subtitle]

    # Assert — no "MOCK" text, and no digits (a count) that edp-api does not emit yet
    assert not any("MOCK" in s for s in subtitles)
    assert not any(any(c.isdigit() for c in s) for s in subtitles)


def test_the_counted_artifacts_show_no_subtitle_until_edp_api_emits_counts() -> None:
    # Arrange + Act + Assert
    for key in (
        ArtifactKind.BOM,
        ArtifactKind.CABLE_HOSE_SCHEDULE,
        ArtifactKind.DTM,
        ArtifactKind.INTERFACE_PLATE,
    ):
        assert key in MOCK_ARTIFACT_METADATA
        assert MOCK_ARTIFACT_METADATA[key].subtitle is None
