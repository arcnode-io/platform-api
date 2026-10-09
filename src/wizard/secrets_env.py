"""/opt/arcnode/secrets.env — where each daemon page leaves its connection
URLs for the EMS containers (and a sysadmin), same file + names as the cloud."""

from pathlib import Path

from src.wizard.wizard_record import VerifyCheck


def save_secrets(path: Path, values: dict[str, str]) -> None:
    """Upsert ``values`` into the env file (0600); other lines are kept."""
    lines = []
    if path.is_file():
        lines = [
            line
            for line in path.read_text().splitlines()
            if line.partition("=")[0] not in values
        ]
    lines += [f"{name}={value}" for name, value in values.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text("\n".join(lines) + "\n")


def read_secret(path: Path, name: str) -> str | None:
    """One saved value, or None when the file or the name isn't there."""
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        if key == name:
            return value
    return None


def saved_check(path: Path, names: list[str]) -> VerifyCheck:
    """The page's last row: its names are in the file, and only root reads it."""
    present = (
        [line.partition("=")[0] for line in path.read_text().splitlines()]
        if path.is_file()
        else []
    )
    missing = [name for name in names if name not in present]
    root_only = path.is_file() and path.stat().st_mode & 0o077 == 0
    detail = f"{path} (root only): {', '.join(names)}"
    if missing:
        detail = f"{path} is missing {', '.join(missing)}"
    elif not root_only:
        detail = f"{path} is readable by other users"
    return VerifyCheck(
        name="Saved for the EMS services",
        ok=not missing and root_only,
        detail=detail,
        # Names only — never print the values, they carry the password.
        hint=f"sudo ls -l {path}; sudo cut -d= -f1 {path}",
    )
