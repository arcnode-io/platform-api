"""The shared credentials template, as the tests read it — imported
explicitly by the HiveMQ tests (no conftest)."""

from pathlib import Path
from typing import Final

TEMPLATE_TEXT: Final[str] = (
    Path(__file__).parents[1] / "compose" / "credentials.template.xml"
).read_text()
