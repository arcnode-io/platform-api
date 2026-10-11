"""The box's own address: the one it uses to reach the internet, which is the one
the LAN and the utility see. Used for the HTTPS cert and the DER public URL."""

import re
from typing import Final

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command

ROUTE_COMMAND: Final[list[str]] = ["ip", "-4", "route", "get", "1.1.1.1"]
SOURCE_ADDRESS: Final[re.Pattern[str]] = re.compile(r"\bsrc (\S+)")


def box_address(run: Runner) -> str:
    """The source address the kernel picks for an outbound route."""
    out = run(Command(args=ROUTE_COMMAND))
    match = SOURCE_ADDRESS.search(out.stdout)
    if match is None:
        raise RuntimeError(f"no source address in: {out.stdout!r}")
    return match.group(1)
