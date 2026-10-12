"""Portal subtitles from edp-api's real per-artifact counts (ArtifactSummary).

A subtitle needs every number it names; a missing one means no subtitle, not a guess.
"""

from collections.abc import Sequence

from src.edp_client.edp_artifacts import ArtifactKind, ArtifactRef


def _first(refs: Sequence[ArtifactRef]) -> ArtifactRef | None:
    return next((r for r in refs if r.summary is not None), None)


def _bus(n: int) -> str:
    return "bus" if n == 1 else "buses"


def subtitle_for(kind: ArtifactKind, refs: Sequence[ArtifactRef]) -> str | None:
    """The one-line description for this artifact's row, or None when counts are missing."""
    if kind == ArtifactKind.INTERFACE_PLATE:
        return _plate_subtitle(refs)
    ref = _first(refs)
    if ref is None or ref.summary is None:
        return None
    s = ref.summary
    if kind == ArtifactKind.BOM and s.line_items is not None and s.vendors is not None:
        return f"{s.line_items} line items · {s.vendors} vendors"
    if (
        kind == ArtifactKind.CABLE_HOSE_SCHEDULE
        and s.runs is not None
        and s.media_kinds is not None
    ):
        return f"{s.runs} runs · {s.media_kinds} media kinds"
    if kind == ArtifactKind.DTM and s.devices is not None and s.buses is not None:
        return f"{s.devices} devices · {s.buses} {_bus(s.buses)}"
    return None


def _plate_subtitle(refs: Sequence[ArtifactRef]) -> str | None:
    """Plates are the sum of each distinct plate id's quantity, kinds the number of ids."""
    quantities: dict[str, int] = {}
    for ref in refs:
        if ref.plate_id is None or ref.summary is None or ref.summary.plates is None:
            return None
        quantities[ref.plate_id] = ref.summary.plates
    if not quantities:
        return None
    total = sum(quantities.values())
    kinds = len(quantities)
    return f"{total} plates · {kinds} kinds"
