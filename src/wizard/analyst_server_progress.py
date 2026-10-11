"""The analyst server's startup stages, read from its own log lines. The
analyst prints each line when that stage finishes, so the page shows real
progress instead of a timer. The seed stages also carry the newest percentage
the analyst logs while it downloads."""

import re
from typing import Final

from pydantic import BaseModel

SEED_PROGRESS: Final[re.Pattern[str]] = re.compile(r"seed progress: (vector|graph) (\d+)%")


class StageProgress(BaseModel):
    """One startup stage: whether its finish line appeared, and the latest download percentage if it's still running."""

    label: str
    done: bool
    percent: int | None = None


# (label, the log text the analyst prints when the stage finishes, which seed it reports on if any)
STAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("Packages installed", "Installed ", None),
    ("Vector data seeded", "vector slice seeded", "vector"),
    ("Graph data seeded", "graph slice seeded", "graph"),
    ("Server listening", "Uvicorn running on http://0.0.0.0:8000", None),
)


def latest_percent(logs: str, seed: str) -> int | None:
    """The newest percentage the analyst logged for this seed, or None if it hasn't started."""
    matches = [int(m.group(2)) for m in SEED_PROGRESS.finditer(logs) if m.group(1) == seed]
    return matches[-1] if matches else None


def stage_status(logs: str) -> list[StageProgress]:
    """Each stage, done when its finish line appears; a running seed carries its latest percentage."""
    stages = []
    for label, finish, seed in STAGES:
        done = finish in logs
        percent = latest_percent(logs, seed) if seed and not done else None
        stages.append(StageProgress(label=label, done=done, percent=percent))
    return stages
