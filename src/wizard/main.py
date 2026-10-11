"""Setup wizard uvicorn entry point.

Standalone — not part of platform-api's own running service. Baked into
the appliance ISO and started by setup.sh's systemd unit, as root (it
writes into another account's ~/.ssh).

On-prem it is plain HTTP: a one-time setup window on the customer's LAN. In the cloud the
wizard serves HTTPS from the box's certificate (self-signed at boot, replaced by a Let's
Encrypt one), because the customer's passwords cross the internet to reach it.
"""

import pwd
from pathlib import Path
from typing import Final, NamedTuple

import uvicorn
from fastapi import FastAPI

from src.wizard.system_runner import run_system_command, stream_system_command
from src.wizard.wizard_config import load_wizard_config
from src.wizard.setup_token import token_for
from src.wizard.wizard_module import WizardModule
from src.wizard.wizard_record import Deployment, SshAccount

BASE_DIR: Final[Path] = Path("/etc/arcnode")
# Written by the provisioning path: setup.sh on-prem, EC2 UserData in the cloud.
CONFIG_PATH: Final[Path] = BASE_DIR / "wizard-cfg.yml"
# What the EMS containers load and mount (src/compose/*/docker-compose.yaml)
# — the same paths the cloud's UserData writes.
EMS_DIR: Final[Path] = Path("/opt/arcnode")
SECRETS_ENV_PATH: Final[Path] = EMS_DIR / "secrets.env"
# ems-analyst's overlay — two pages write it (Ollama, Site).
ANALYST_CFG_PATH: Final[Path] = EMS_DIR / "analyst-cfg.customer.yml"
PORT: Final[int] = 8080
# All interfaces on purpose: the appliance's one-time setup window is reached from the LAN.
BIND_HOST: Final[str] = "0.0.0.0"  # noqa: S104  # nosec B104
# Idle browser connections stay open this long, so a step clicked after reading
# a page doesn't hit a connection uvicorn already closed (its default is 5s).
KEEP_ALIVE_SECONDS: Final[int] = 75
TLS_DIR: Final[Path] = EMS_DIR / "tls"
TLS_CERT_FILE: Final[str] = "server.pem"
TLS_KEY_FILE: Final[str] = "server-key.pem"
# Debian's adduser gives the first account created in the installer
# FIRST_UID=1000 (/etc/adduser.conf) — that's the customer's login.
INSTALLER_ACCOUNT_UID: Final[int] = 1000


class TlsFiles(NamedTuple):
    """The certificate and key the wizard serves HTTPS with."""

    certfile: Path
    keyfile: Path


def tls_files(deployment: Deployment, tls_dir: Path = TLS_DIR) -> TlsFiles | None:
    """HTTPS in the cloud, plain HTTP on-prem. A cloud box without its certificate fails to
    start (FileNotFoundError) rather than serving customer passwords in the clear."""
    if deployment != Deployment.CLOUD:
        return None
    files = TlsFiles(tls_dir / TLS_CERT_FILE, tls_dir / TLS_KEY_FILE)
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f"cloud wizard needs its certificate: {path}")
    return files


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
            ems_dir=EMS_DIR,
            account=installer_account(),
            config=config,
            run=run_system_command,
            stream=stream_system_command,
            setup_token=token_for(config.deployment, SECRETS_ENV_PATH),
        ).router
    )
    # Appliance-local, one-time setup window — binding all interfaces is the point.
    tls = tls_files(config.deployment)
    uvicorn.run(
        app,
        host=BIND_HOST,
        port=PORT,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
        ssl_certfile=str(tls.certfile) if tls else None,
        ssl_keyfile=str(tls.keyfile) if tls else None,
    )


if __name__ == "__main__":
    main()
