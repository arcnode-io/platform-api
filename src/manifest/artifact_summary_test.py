"""Portal subtitles from edp-api's real per-artifact counts. No summary, no subtitle."""

from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef, ArtifactSummary
from src.manifest.artifact_summary import subtitle_for

URL = "https://x/y"


def _ref(
    kind: ArtifactKind,
    fmt: str,
    summary: ArtifactSummary | None = None,
    plate_id: str | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        kind=kind, format=fmt, url=URL, plate_id=plate_id, summary=summary
    )


def test_bom_reads_line_items_and_vendors_from_its_summary() -> None:
    # Arrange
    refs = [
        _ref(ArtifactKind.BOM, "json", ArtifactSummary(line_items=19, vendors=11)),
        _ref(ArtifactKind.BOM, "xlsx", ArtifactSummary(line_items=19, vendors=11)),
    ]

    # Act + Assert
    assert subtitle_for(ArtifactKind.BOM, refs) == "19 line items · 11 vendors"


def test_cable_and_hose_reads_runs_and_media_kinds() -> None:
    refs = [
        _ref(
            ArtifactKind.CABLE_HOSE_SCHEDULE,
            "json",
            ArtifactSummary(runs=81, media_kinds=4),
        )
    ]

    assert (
        subtitle_for(ArtifactKind.CABLE_HOSE_SCHEDULE, refs)
        == "81 runs · 4 media kinds"
    )


def test_dtm_reads_devices_and_buses_with_singular_for_one() -> None:
    refs = [_ref(ArtifactKind.DTM, "json", ArtifactSummary(devices=36, buses=1))]

    assert subtitle_for(ArtifactKind.DTM, refs) == "36 devices · 1 bus"


def test_plates_total_the_quantity_of_each_distinct_plate_id() -> None:
    """edp-api sets each plate's quantity on both its step and dxf refs; the count of plates is the
    sum over distinct plate ids, and the kinds are how many distinct ids there are."""
    refs = [
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "step",
            ArtifactSummary(plates=2),
            plate_id="CG",
        ),
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "dxf",
            ArtifactSummary(plates=2),
            plate_id="CG",
        ),
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "step",
            ArtifactSummary(plates=2),
            plate_id="CD",
        ),
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "dxf",
            ArtifactSummary(plates=2),
            plate_id="CD",
        ),
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "step",
            ArtifactSummary(plates=1),
            plate_id="BG",
        ),
        _ref(
            ArtifactKind.INTERFACE_PLATE,
            "dxf",
            ArtifactSummary(plates=1),
            plate_id="BG",
        ),
    ]

    assert subtitle_for(ArtifactKind.INTERFACE_PLATE, refs) == "5 plates · 3 kinds"


def test_no_summary_means_no_subtitle() -> None:
    """Until edp-api fills the summary (it is null on the POST response), nothing is shown."""
    assert subtitle_for(ArtifactKind.BOM, [_ref(ArtifactKind.BOM, "json")]) is None


def test_a_partly_filled_summary_is_not_shown_as_if_complete() -> None:
    refs = [
        _ref(ArtifactKind.BOM, "json", ArtifactSummary(line_items=19, vendors=None))
    ]

    assert subtitle_for(ArtifactKind.BOM, refs) is None


def test_kinds_without_counts_have_no_subtitle() -> None:
    refs = [_ref(ArtifactKind.SLD, "pdf", ArtifactSummary(line_items=3))]

    assert subtitle_for(ArtifactKind.SLD, refs) is None
