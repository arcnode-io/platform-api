"""Which wizard pages exist, and which are done.

One page per daemon, in install-dependency order. Each page writes its own
done marker when its verification passes, so setup survives a reboot
mid-way and resumes at the first unfinished page.
"""

from pathlib import Path
from typing import Final

STEPS: Final[tuple[str, ...]] = (
    # The hardware check is the root of the dependency graph.
    "preflight",
    # Right after the hardware check: the customer confirms this is their site's
    # ISO, which hands the order to every EMS container that runs later.
    "site",
    "ssh",
    "docker",
    "postgres",
    "neo4j",
    "ollama",
    "hivemq",
    "telemetry",
    "device_api",
    "der_control_api",
    "industrial_gateway",
    "hmi",
    # Optional: a certificate from the customer's own CA for the HMI's name. Right
    # after the HMI page so the customer sees the operator screen secured next.
    "https",
    "mlflow",
    "analyst_model",
    "analyst_server",
    "prometheus",
    "grafana",
    # Last on purpose: password SSH stays as the recovery path until everything else is in.
    "ssh_lockdown",
)


class StepAlreadyDoneError(Exception):
    """The page's verification already passed — the API refuses a redo, not
    just the UI."""


class StepTracker:
    """Done markers for the wizard's pages, one file per page."""

    def __init__(self, *, steps_dir: Path) -> None:
        self._steps_dir = steps_dir
        self.steps: tuple[str, ...] = STEPS

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
        """The whole wizard is finished — it 404s from here on."""
        return all(self.is_done(step) for step in self.steps)
