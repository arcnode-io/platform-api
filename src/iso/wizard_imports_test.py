"""Every module the wizard imports from outside src/wizard must be copied into
the ISO, or the box's wizard crashes at boot (ModuleNotFoundError)."""

import re
from pathlib import Path

REPO: Path = Path(__file__).resolve().parents[2]
BUILD_SCRIPT: Path = REPO / "src" / "iso" / "build.sh"
WIZARD_DIR: Path = REPO / "src" / "wizard"
IMPORT: re.Pattern[str] = re.compile(r"^from (src\.[\w.]+) import", re.MULTILINE)


def test_every_shared_module_the_wizard_imports_is_in_the_iso() -> None:
    # Arrange
    build_script = BUILD_SCRIPT.read_text()
    shared = set()
    for path in WIZARD_DIR.rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        for module in IMPORT.findall(path.read_text()):
            if not module.startswith("src.wizard"):
                shared.add(module)

    # Act
    missing = [
        m
        for m in sorted(shared)
        if f"/wizard-src/{m.replace('.', '/')}.py" not in build_script
    ]

    # Assert
    assert missing == []
