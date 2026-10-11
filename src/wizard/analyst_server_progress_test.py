"""Unit tests for the analyst server's progress stages — each stage is done
when the log line the analyst code prints for it appears."""

from src.wizard.analyst_server_progress import stage_status

LOG = (
    "Installed 42 packages in 37ms\n"
    "INFO: seeding vector slice from https://arcnode-public/seed/vector-cloud.sql.gz\n"
    "INFO: vector slice seeded\n"
)


def test_stages_before_the_log_line_are_not_done() -> None:
    # Arrange — the vector seed has started but not finished

    # Act
    stages = stage_status("Installed 42 packages in 37ms\n")

    # Assert
    assert [(s.label, s.done) for s in stages] == [
        ("Packages installed", True),
        ("Vector data seeded", False),
        ("Graph data seeded", False),
        ("Server listening", False),
    ]


def test_a_finished_seed_stage_is_done() -> None:
    # Arrange + Act
    stages = stage_status(LOG)

    # Assert
    assert [s.done for s in stages] == [True, True, False, False]


def test_all_stages_done_once_uvicorn_is_listening() -> None:
    # Arrange
    logs = (
        LOG
        + "INFO: graph slice seeded\nINFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)\n"
    )

    # Act
    stages = stage_status(logs)

    # Assert
    assert all(s.done for s in stages)


def test_a_seed_in_progress_reports_its_latest_percentage() -> None:
    # Arrange — the vector seed has reached 40%, its finish line hasn't printed yet
    logs = (
        "seed progress: vector 10% (30 MiB of 300 MiB)\n"
        "seed progress: vector 40% (120 MiB of 300 MiB)\n"
    )

    # Act
    stages = stage_status(logs)

    # Assert — still running, showing the newest percentage
    vector = stages[1]
    assert (vector.done, vector.percent) == (False, 40)


def test_a_finished_seed_has_no_percentage() -> None:
    # Arrange
    logs = (
        "seed progress: vector 100% (300 MiB of 300 MiB)\nINFO: vector slice seeded\n"
    )

    # Act
    stages = stage_status(logs)

    # Assert
    assert (stages[1].done, stages[1].percent) == (True, None)


def test_a_running_seed_estimates_its_time_left_from_its_rate() -> None:
    # Arrange — 10% at 10:00:00 and 20% at 10:01:00: 10% a minute, 80% left, so 8 minutes
    logs = (
        "2026-10-10T10:00:00.000000Z  INFO: seed progress: vector 10% (30 MiB of 300 MiB)\n"
        "2026-10-10T10:01:00.000000Z  INFO: seed progress: vector 20% (60 MiB of 300 MiB)\n"
    )

    # Act
    vector = stage_status(logs)[1]

    # Assert
    assert vector.eta_seconds == 480


def test_one_progress_line_gives_no_estimate_yet() -> None:
    # Arrange — a single sample has no rate
    logs = "2026-10-10T10:00:00.000000Z  INFO: seed progress: graph 5% (30 MiB of 630 MiB)\n"

    # Act
    graph = stage_status(logs)[2]

    # Assert
    assert graph.eta_seconds is None
