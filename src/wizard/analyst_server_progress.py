"""The analyst server's startup stages, read from its own log lines. The
analyst prints a line when each stage finishes, so the page shows real progress
instead of a timer. A seed stage has two phases the analyst reports separately:
it downloads a dump (`seed progress: <seed> N% (X MiB of Y MiB)`), then imports
it (`seed import: <seed> N% (A of B statements)`), so the import shows its own
progress instead of sitting at the download's "100%"."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel

# Optional sizes: older analyst images log only the percentage.
SEED_PROGRESS: Final[re.Pattern[str]] = re.compile(
    r"seed progress: (vector|graph) (\d+)%(?: \((\d+) MiB of (\d+) MiB\))?"
)
SEED_IMPORT: Final[re.Pattern[str]] = re.compile(r"seed import: (vector|graph) (\d+)%")
# The analyst's own timestamp leads each line; fractional seconds may be longer than datetime takes.
LOG_TIME: Final[re.Pattern[str]] = re.compile(r"(\d{4}-\d{2}-\d{2}T[\d:.]+)Z")


class StagePhase(StrEnum):
    """Where a stage is: not started, downloading its dump, importing it, or finished."""

    WAITING = "waiting"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    DONE = "done"


class StageProgress(BaseModel):
    """One startup stage. `percent` is the current phase's percentage (None when the
    phase has no number to quote, e.g. an import the analyst doesn't report on);
    sizes are the download's, in MiB."""

    label: str
    done: bool
    phase: StagePhase
    percent: int | None = None
    eta_seconds: int | None = None
    mib_done: int | None = None
    mib_total: int | None = None


# (label, the log text the analyst prints when the stage finishes, which seed it reports on if any)
STAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("Packages installed", "Installed ", None),
    ("Vector data seeded", "vector slice seeded", "vector"),
    ("Graph data seeded", "graph slice seeded", "graph"),
    ("Server listening", "Uvicorn running on http://0.0.0.0:8000", None),
)


def _samples(
    logs: str, pattern: re.Pattern[str], seed: str
) -> list[tuple[datetime | None, int, re.Match[str]]]:
    """Every line of this seed matching `pattern`: its timestamp (if any), percent, match."""
    found = []
    for line in logs.splitlines():
        match = pattern.search(line)
        if match is None or match.group(1) != seed:
            continue
        stamp = LOG_TIME.search(line)
        when = datetime.fromisoformat(stamp.group(1)[:26]) if stamp else None
        found.append((when, int(match.group(2)), match))
    return found


def _eta(samples: list[tuple[datetime | None, int, re.Match[str]]]) -> int | None:
    """Seconds left, from the first and newest timestamped samples. None until the
    percentage has moved between two timestamped lines."""
    stamped = [(when, pct) for when, pct, _ in samples if when is not None]
    if len(stamped) < 2:
        return None
    (first_at, first_pct), (last_at, last_pct) = stamped[0], stamped[-1]
    if last_pct <= first_pct:
        return None
    rate = (last_pct - first_pct) / (last_at - first_at).total_seconds()
    return round((100 - last_pct) / rate)


def _seed_stage(label: str, logs: str, seed: str) -> StageProgress:
    """A seed stage that hasn't printed its finish line: waiting, downloading or importing."""
    imports = _samples(logs, SEED_IMPORT, seed)
    downloads = _samples(logs, SEED_PROGRESS, seed)
    if imports:
        # Reason: the analyst reports the import itself, so quote its own percentage.
        return StageProgress(
            label=label,
            done=False,
            phase=StagePhase.IMPORTING,
            percent=imports[-1][1],
            eta_seconds=_eta(imports),
        )
    if downloads and downloads[-1][1] >= 100:
        # Reason: the download is finished and the analyst reports nothing while it
        # applies the dump, so there is no honest percentage or estimate to show.
        return StageProgress(label=label, done=False, phase=StagePhase.IMPORTING)
    if downloads:
        newest = downloads[-1][2]
        done_mib, total_mib = newest.group(3), newest.group(4)
        return StageProgress(
            label=label,
            done=False,
            phase=StagePhase.DOWNLOADING,
            percent=downloads[-1][1],
            eta_seconds=_eta(downloads),
            mib_done=int(done_mib) if done_mib else None,
            mib_total=int(total_mib) if total_mib else None,
        )
    return StageProgress(label=label, done=False, phase=StagePhase.WAITING)


def stage_status(logs: str) -> list[StageProgress]:
    """Each stage: done when its finish line appears, else where its seed has got to."""
    stages = []
    for label, finish, seed in STAGES:
        if finish in logs:
            stages.append(StageProgress(label=label, done=True, phase=StagePhase.DONE))
        elif seed is not None:
            stages.append(_seed_stage(label, logs, seed))
        else:
            stages.append(
                StageProgress(label=label, done=False, phase=StagePhase.WAITING)
            )
    return stages
