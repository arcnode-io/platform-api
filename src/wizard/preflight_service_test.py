"""Unit tests for the hardware check page — the gate, not the checks
(those are in preflight_verify_test)."""

from pathlib import Path

import pytest

from src.wizard.preflight_service import PreflightService
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import HardwareMinimums
from src.wizard.wizard_steps import StepAlreadyDoneError


def _service(tmp_path: Path, runner: FakeRunner) -> PreflightService:
    return PreflightService(
        tracker=tracker(tmp_path),
        minimums=HardwareMinimums(
            vcpus=8, memory_gib=64, gpus=1, gpu_memory_gb=48, disk_gb=1000
        ),
        run=runner,
    )


def test_a_box_that_meets_the_spec_unlocks_the_next_page(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeRunner())

    # Act
    actual = service.apply()

    # Assert
    assert actual.verified is True
    assert tracker(tmp_path).completed() == ["preflight"]


def test_a_box_without_a_gpu_is_blocked_and_can_be_rechecked(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.outputs["lspci"] = ok(
        "00:02.0 VGA compatible controller [0300]: Intel UHD 630\n"
    )
    service = _service(tmp_path, runner)

    # Act
    actual = service.apply()

    # Assert: blocked, and the page stays open for a re-check
    assert actual.verified is False
    assert tracker(tmp_path).completed() == []


def test_a_passed_check_is_not_rerun(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, FakeRunner())
    service.apply()

    # Act / Assert
    with pytest.raises(StepAlreadyDoneError):
        service.apply()
