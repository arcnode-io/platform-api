"""Setup wizard uvicorn entry point.

Standalone — not part of platform-api's own running service. Baked into
the appliance ISO (started by late_command) and the cloud AMI (started by
EC2 UserData), via its own versioned artifact publish, not platform-api's
`build` job. See src/wizard/README.md.

HTTPS gap, flagged not hidden: this server itself binds plain HTTP. It
can't serve itself over the TLS cert it hasn't generated yet (that's
literally step 3's job) — chicken-and-egg. It's a one-time, short-lived,
local-network setup window, not the long-running HMI this sets up for.
Revisit if that stops being an acceptable tradeoff.
"""

from pathlib import Path
from typing import Final

import uvicorn
from fastapi import FastAPI

from src.wizard.wizard_module import WizardModule

BASE_DIR: Final[Path] = Path("/etc/arcnode")
PORT: Final[int] = 8080

wizard_module = WizardModule(base_dir=BASE_DIR)
app = FastAPI(title="arcnode-setup-wizard")
app.include_router(wizard_module.router)


def main() -> None:
    """Boot the wizard's uvicorn server."""
    # Appliance-local, one-time setup window — binding all interfaces is the point.
    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
