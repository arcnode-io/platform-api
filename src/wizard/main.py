"""Setup wizard uvicorn entry point.

Standalone — not part of platform-api's own running service. Baked into
the appliance ISO and started by setup.sh's systemd unit, as root (it
writes into another account's ~/.ssh).

Plain HTTP: a one-time, local-network setup window, and there's no cert
to serve yet. Revisit if that stops being an acceptable tradeoff.
"""

import pwd
from pathlib import Path
from typing import Final

import uvicorn
from fastapi import FastAPI

from src.wizard.system_runner import run_system_command, stream_system_command
from src.wizard.wizard_config import load_wizard_config
from src.wizard.wizard_module import WizardModule
from src.wizard.wizard_record import SshAccount

BASE_DIR: Final[Path] = Path("/etc/arcnode")
# Written by the provisioning path: setup.sh on-prem, EC2 UserData in the cloud.
CONFIG_PATH: Final[Path] = BASE_DIR / "wizard-cfg.yml"
# What every EMS container loads (src/compose/*/docker-compose.yaml) — the
# same path the cloud's UserData writes.
SECRETS_ENV_PATH: Final[Path] = Path("/opt/arcnode/secrets.env")
# ems-analyst's overlay — the compose files mount it; the cloud writes it too.
ANALYST_CFG_PATH: Final[Path] = Path("/opt/arcnode/analyst-cfg.customer.yml")
PORT: Final[int] = 8080
# Debian's adduser gives the first account created in the installer
# FIRST_UID=1000 (/etc/adduser.conf) — that's the customer's login.
INSTALLER_ACCOUNT_UID: Final[int] = 1000


def installer_account() -> SshAccount:
    """The account the customer created in the Debian installer."""
    entry = pwd.getpwuid(INSTALLER_ACCOUNT_UID)
    return SshAccount(
        name=entry.pw_name, home=Path(entry.pw_dir), uid=entry.pw_uid, gid=entry.pw_gid
    )


def main() -> None:
    """Boot the wizard's uvicorn server."""
    app = FastAPI(title="arcnode-setup-wizard")
    config = load_wizard_config(CONFIG_PATH)
    app.include_router(
        WizardModule(
            base_dir=BASE_DIR,
            secrets_env_path=SECRETS_ENV_PATH,
            analyst_cfg_path=ANALYST_CFG_PATH,
            account=installer_account(),
            config=config,
            run=run_system_command,
            stream=stream_system_command,
        ).router
    )
    # Appliance-local, one-time setup window — binding all interfaces is the point.
    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104


if __name__ == "__main__":
    main()
