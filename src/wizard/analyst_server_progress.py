"""The analyst server's startup stages, read from its own log lines. The
analyst prints each line when that stage finishes, so the page shows real
progress instead of a timer."""

from typing import Final, NamedTuple


class StageProgress(NamedTuple):
    """One startup stage and whether its log line has appeared."""

    label: str
    done: bool


# (label, the log text the analyst prints when the stage finishes)
STAGES: Final[tuple[tuple[str, str], ...]] = (
    ("Packages installed", "Installed "),
    ("Vector data seeded", "vector slice seeded"),
    ("Graph data seeded", "graph slice seeded"),
    ("Server listening", "Uvicorn running on http://0.0.0.0:8000"),
)


def stage_status(logs: str) -> list[StageProgress]:
    """Each stage, done when its line appears in the container's logs."""
    return [StageProgress(label, needle in logs) for label, needle in STAGES]
