"""The wizard's boot-time requirements must pin the same versions uv.lock resolves,
so the box runs what CI tested."""

import re
from pathlib import Path

REPO: Path = Path(__file__).resolve().parents[2]
REQUIREMENTS: Path = REPO / "src" / "wizard" / "requirements.txt"
UV_LOCK: Path = REPO / "uv.lock"
WIZARD_PACKAGES: tuple[str, ...] = ("fastapi", "uvicorn", "pydantic", "pyyaml")


def locked_version(package: str) -> str:
    """The version uv.lock resolves for one package."""
    match = re.search(
        rf'^name = "{package}"\nversion = "([^"]+)"$', UV_LOCK.read_text(), re.MULTILINE
    )
    assert match is not None
    return match.group(1)


def test_every_wizard_package_is_pinned_to_the_locked_version() -> None:
    # Arrange
    pinned = REQUIREMENTS.read_text().splitlines()

    # Act
    expected = [f"{p}=={locked_version(p)}" for p in WIZARD_PACKAGES]

    # Assert
    assert sorted(pinned) == sorted(expected)
