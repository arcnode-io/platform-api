"""Which wizard pages exist per deployment, and which are done.

One page per daemon, in install-dependency order. Each page writes its own
done marker when its verification passes, so setup survives a reboot
mid-way and resumes at the first unfinished page.
"""

from pathlib import Path
from typing import Final

from src.wizard.wizard_record import Deployment

STEPS_BY_DEPLOYMENT: Final[dict[Deployment, tuple[str, ...]]] = {
    # The hardware check is the root of the dependency graph — first everywhere.
    # Then the order's site, which every EMS container reads.
    Deployment.ON_PREM: (
        "preflight",
        "ssh",
        "docker",
        "postgres",
        "neo4j",
        "ollama",
        "site",
    ),
    # EC2 set SSH + Docker up; databases are managed services in the cloud,
    # the LLM is Bedrock.
    Deployment.CLOUD: ("preflight",),
}


class StepAlreadyDoneError(Exception):
    """The page's verification already passed — the API refuses a redo, not
    just the UI."""


class StepTracker:
    """Done markers for the wizard's pages, one file per page."""

    def __init__(self, *, steps_dir: Path, deployment: Deployment) -> None:
        self._steps_dir = steps_dir
        self.steps: tuple[str, ...] = STEPS_BY_DEPLOYMENT[deployment]

    def is_done(self, step: str) -> bool:
        """True once this page's verification has passed."""
        return (self._steps_dir / f"{step}.done").exists()

    def mark_done(self, step: str) -> None:
        """Record that this page's verification passed."""
        self._steps_dir.mkdir(parents=True, exist_ok=True)
        (self._steps_dir / f"{step}.done").touch()

    def completed(self) -> list[str]:
        """Done pages, in page order."""
        return [step for step in self.steps if self.is_done(step)]

    def all_done(self) -> bool:
        """The whole wizard is finished — it 404s from here on. A deployment
        with no pages is never 'finished'; its page says there's nothing to do."""
        return bool(self.steps) and all(self.is_done(step) for step in self.steps)
