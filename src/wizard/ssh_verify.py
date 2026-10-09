"""Playbook-style verification for the SSH step — each check a row the UI
shows. The box can't prove a login (only the customer has the private key),
so the last row shows the installed key's fingerprint to compare against
``ssh-keygen -lf private-key.pem`` on their machine."""

import shutil
import subprocess  # nosec B404 — ssh-keygen below, resolved path, no shell

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, SshAccount, VerifyCheck


def verify_ssh(
    account: SshAccount, run: Runner, installed_key: str
) -> list[VerifyCheck]:
    """sshd running → answering → allowing key login → our key in place."""
    return [
        _daemon_running(run),
        _answers_on_port_22(run),
        _key_login_allowed(account, run),
        _key_installed(account, installed_key),
    ]


def _daemon_running(run: Runner) -> VerifyCheck:
    out = run(Command(args=["systemctl", "is-active", "ssh"]))
    state = out.stdout.strip() or f"exit {out.returncode}"
    return VerifyCheck(
        name="SSH daemon running",
        ok=state == "active",
        detail=state,
        hint="sudo systemctl status ssh && sudo sshd -t",
    )


def _answers_on_port_22(run: Runner) -> VerifyCheck:
    # A real SSH handshake (host key returned), not just an open socket.
    out = run(Command(args=["ssh-keyscan", "localhost"]))
    lines = [
        line for line in out.stdout.splitlines() if line and not line.startswith("#")
    ]
    ok = out.returncode == 0 and bool(lines)
    detail = (
        f"host key {lines[0].split()[1]}" if ok else "no SSH answer on localhost:22"
    )
    return VerifyCheck(
        name="Answers SSH on port 22",
        ok=ok,
        detail=detail,
        hint="sudo ss -ltnp | grep sshd; sudo journalctl -u ssh",
    )


def _key_login_allowed(account: SshAccount, run: Runner) -> VerifyCheck:
    # sshd -T prints the effective config for this connection, Match blocks included.
    out = run(
        Command(
            args=[
                "sshd",
                "-T",
                "-C",
                f"user={account.name},host=localhost,addr=127.0.0.1",
            ]
        )
    )
    setting = next(
        (
            line
            for line in out.stdout.splitlines()
            if line.startswith("pubkeyauthentication ")
        ),
        out.stdout.strip() or f"exit {out.returncode}",
    )
    return VerifyCheck(
        name=f"Key login allowed for {account.name}",
        ok=setting == "pubkeyauthentication yes",
        detail=setting,
        hint=(
            f"sudo sshd -T -C user={account.name},host=localhost,addr=127.0.0.1"
            " | grep pubkey; grep -ri pubkey /etc/ssh/sshd_config /etc/ssh/sshd_config.d/"
        ),
    )


def _key_installed(account: SshAccount, key: str) -> VerifyCheck:
    name = "Your key is installed"
    hint = f"sudo ls -la ~{account.name}/.ssh; sudo cat ~{account.name}/.ssh/authorized_keys"
    ssh_dir = account.home / ".ssh"
    authorized_keys = ssh_dir / "authorized_keys"
    if (
        not authorized_keys.is_file()
        or key not in authorized_keys.read_text().splitlines()
    ):
        return VerifyCheck(
            name=name, ok=False, detail=f"not in {authorized_keys}", hint=hint
        )
    # Reason: sshd's StrictModes ignores the file if these are off.
    for path, mode in ((ssh_dir, 0o700), (authorized_keys, 0o600)):
        stat = path.stat()
        if stat.st_mode & 0o777 != mode or stat.st_uid != account.uid:
            return VerifyCheck(
                name=name,
                ok=False,
                detail=f"{path} must be {oct(mode)[2:]}, owned by {account.name}",
                hint=hint,
            )
    return VerifyCheck(
        name=name,
        ok=True,
        detail=f"{_fingerprint(key)} — should match: ssh-keygen -lf private-key.pem",
        hint=hint,
    )


def _fingerprint(key: str) -> str:
    """SHA256 fingerprint, same format ssh-keygen -lf prints on their machine."""
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        raise RuntimeError("ssh-keygen not found on PATH")
    result = (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [ssh_keygen, "-l", "-f", "/dev/stdin"],
            input=key,
            capture_output=True,
            text=True,
            check=True,
        )
    )
    return result.stdout.split()[1]
