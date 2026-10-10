"""The one-time token that gates the cloud wizard. The stack output and the EC2
console log both show it; the browser sends it on every change."""

import secrets
from pathlib import Path
from typing import Final

# Reason: a request header name, not a secret value.
TOKEN_HEADER: Final[str] = "X-Setup-Token"  # noqa: S105


def read_or_create_token(path: Path) -> str:
    """The token on disk, made on first use with 0600 so only root reads it."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(secrets.token_urlsafe(32))
    return path.read_text().strip()


def setup_token_from_env_file(path: Path) -> str | None:
    """The SETUP_TOKEN line in secrets.env, or None when UserData didn't write one."""
    for line in path.read_text().splitlines():
        if line.startswith("SETUP_TOKEN="):
            return line.removeprefix("SETUP_TOKEN=")
    return None
