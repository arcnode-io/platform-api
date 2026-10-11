"""The analyst server's startup stages, read from its own log lines. The
analyst prints each line when that stage finishes, so the page shows real
progress instead of a timer. The seed stages also carry the newest percentage
the analyst logs while it downloads."""

import re
from datetime import datetime
from typing import Final

from pydantic import BaseModel

SEED_PROGRESS: Final[re.Pattern[str]] = re.compile(
    r"seed progress: (vector|graph) (\d+)%"
)
# The analyst's own timestamp leads each line; fractional seconds may be longer than datetime takes.
LOG_TIME: Final[re.Pattern[str]] = re.compile(r"(\d{4}-\d{2}-\d{2}T[\d:.]+)Z")


class StageProgress(BaseModel):
    """One startup stage: whether its finish line appeared, and the latest download percentage if it's still running."""

    label: str
    done: bool
    percent: int | None = None
    eta_seconds: int | None = None


# (label, the log text the analyst prints when the stage finishes, which seed it reports on if any)
STAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("Packages installed", "Installed ", None),
    ("Vector data seeded", "vector slice seeded", "vector"),
    ("Graph data seeded", "graph slice seeded", "graph"),
    ("Server listening", "Uvicorn running on http://0.0.0.0:8000", None),
)


def latest_percent(logs: str, seed: str) -> int | None:
    """The newest percentage the analyst logged for this seed, or None if it hasn't started."""
    matches = [
        int(m.group(2)) for m in SEED_PROGRESS.finditer(logs) if m.group(1) == seed
    ]
    return matches[-1] if matches else None


def eta_seconds(logs: str, seed: str) -> int | None:
    """Seconds left for this seed, from its first and newest progress lines. None until the
    percentage has moved between two timestamped lines."""
    samples = []
    for line in logs.splitlines():
        match = SEED_PROGRESS.search(line)
        stamp = LOG_TIME.search(line)
        if match and stamp and match.group(1) == seed:
            when = datetime.fromisoformat(stamp.group(1)[:26])
            samples.append((when, int(match.group(2))))
    if len(samples) < 2:
        return None
    (first_at, first_pct), (last_at, last_pct) = samples[0], samples[-1]
    if last_pct <= first_pct:
        return None
    elapsed = (last_at - first_at).total_seconds()
    rate = (last_pct - first_pct) / elapsed
    return round((100 - last_pct) / rate)


def stage_status(logs: str) -> list[StageProgress]:
    """Each stage, done when its finish line appears; a running seed carries its latest percentage and time left."""
    stages = []
    for label, finish, seed in STAGES:
        done = finish in logs
        running = seed is not None and not done
        percent = latest_percent(logs, seed) if running else None
        eta = eta_seconds(logs, seed) if running else None
        stages.append(
            StageProgress(label=label, done=done, percent=percent, eta_seconds=eta)
        )
    return stages
