"""Unit tests for the wizard's per-page done markers."""

from pathlib import Path

from src.wizard.wizard_record import Deployment
from src.wizard.wizard_steps import StepTracker


def test_on_prem_closes_only_after_every_page_is_done(tmp_path: Path) -> None:
    # Arrange
    tracker = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM)

    # Act
    tracker.mark_done("preflight")
    tracker.mark_done("ssh")

    # Assert: the hardware check and SSH aren't the whole wizard
    assert (tracker.completed(), tracker.all_done()) == (["preflight", "ssh"], False)
    tracker.mark_done("docker")
    tracker.mark_done("postgres")
    assert not tracker.all_done()
    tracker.mark_done("neo4j")
    assert not tracker.all_done()
    tracker.mark_done("ollama")
    assert tracker.all_done()


def test_done_survives_a_restart(tmp_path: Path) -> None:
    # Arrange: the wizard process restarts mid-setup (reboot, crash)
    StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM).mark_done(
        "ssh"
    )

    # Act
    actual = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.ON_PREM)

    # Assert
    assert actual.is_done("ssh")
    assert not actual.is_done("postgres")


def test_cloud_starts_with_the_hardware_check_too(tmp_path: Path) -> None:
    # Arrange: an EC2 instance type can be undersized just like a server
    tracker = StepTracker(steps_dir=tmp_path / "steps", deployment=Deployment.CLOUD)

    # Act
    tracker.mark_done("preflight")

    # Assert
    assert (tracker.steps, tracker.all_done()) == (("preflight",), True)
