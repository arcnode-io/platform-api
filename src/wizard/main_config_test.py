"""The wizard's server settings. Browsers hold idle connections between steps,
so uvicorn must keep them open longer than a person takes to read a page."""

from src.wizard.main import KEEP_ALIVE_SECONDS


def test_keep_alive_outlasts_a_person_reading_a_step() -> None:
    # Arrange — uvicorn's own default is 5 seconds, which drops a browser's idle connection

    # Act
    keep_alive = KEEP_ALIVE_SECONDS

    # Assert
    assert keep_alive >= 60
