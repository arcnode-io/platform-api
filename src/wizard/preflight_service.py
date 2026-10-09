"""The hardware check page: run the checks, unlock the next page only
when the box meets wizard-cfg.yml's minimums."""

from src.wizard.preflight_verify import verify_hardware
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import HardwareMinimums, StepResult
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker


class PreflightService:
    """Hard gate: no "continue anyway" — GPU and NVMe are required."""

    def __init__(
        self, *, tracker: StepTracker, minimums: HardwareMinimums, run: Runner
    ) -> None:
        self._tracker = tracker
        self._minimums = minimums
        self._run = run

    def apply(self) -> StepResult:
        """Check the hardware; mark the page done only if every check passes."""
        if self._tracker.is_done("preflight"):
            raise StepAlreadyDoneError("the hardware check already passed")
        checks = verify_hardware(self._run, self._minimums)
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("preflight")
        return StepResult(verified=verified, checks=checks)
