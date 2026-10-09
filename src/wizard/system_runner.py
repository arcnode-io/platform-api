"""Runs fixed system commands for the wizard's install + verify steps.

Injected everywhere (a fake in tests) because the real commands need root
and real daemons. Secrets go in through ``input``/``env``, never ``args``
— argv is visible to every user via ``ps``.
"""

import os
import shutil
import subprocess  # nosec B404 — fixed-arg commands below, resolved paths, no shell
from collections.abc import Callable

from src.wizard.wizard_record import Command, CommandOutput

Runner = Callable[[Command], CommandOutput]


def run_system_command(command: Command) -> CommandOutput:
    """Real runner: a missing binary is a failed result, not a crash."""
    binary = shutil.which(command.args[0])
    if binary is None:
        return CommandOutput(returncode=127, stdout=f"{command.args[0]} not found")
    result = (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [binary, *command.args[1:]],
            input=command.input,
            env={**os.environ, **command.env},
            capture_output=True,
            text=True,
            check=False,
        )
    )
    return CommandOutput(
        returncode=result.returncode, stdout=result.stdout or result.stderr
    )
