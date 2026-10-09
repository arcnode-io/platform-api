"""Test fixtures for the wizard — imported explicitly by its *_test.py
files (no conftest)."""

import os
import shutil
import subprocess  # nosec B404 — ssh-keygen in tests, no shell
from pathlib import Path

from src.wizard.neo4j_service import Neo4jService
from src.wizard.postgres_service import PostgresService
from src.wizard.ssh_service import SshService
from src.wizard.wizard_record import Command, CommandOutput, Deployment, SshAccount
from src.wizard.wizard_steps import StepTracker

SSH_KEYGEN = shutil.which("ssh-keygen")


def ssh_keygen(*args: str) -> str:
    """Run the real ssh-keygen; return stdout."""
    assert SSH_KEYGEN is not None, "ssh-keygen not found on PATH"
    return (
        subprocess.run(  # noqa: S603  # nosec B603 — resolved absolute path, fixed args
            [SSH_KEYGEN, *args], check=True, capture_output=True, text=True
        ).stdout
    )


def ec2_style_pem(tmp_path: Path) -> tuple[str, str]:
    """An RSA key in PEM format, like an EC2 .pem: (private PEM, public line).
    The private key is written to ``tmp_path / "my-key.pem"``."""
    key_path = tmp_path / "my-key.pem"
    ssh_keygen(
        "-q", "-t", "rsa", "-b", "2048", "-m", "PEM", "-N", "", "-f", str(key_path)
    )
    return key_path.read_text(), ssh_keygen("-y", "-f", str(key_path)).strip()


def ok(stdout: str) -> CommandOutput:
    """A successful command's output."""
    return CommandOutput(returncode=0, stdout=stdout)


class FakeRunner:
    """Stands in for systemctl / ssh-keyscan / sshd -T / psql and the
    hardware probes, which need root, real daemons and real hardware. Healthy by default; a test breaks one.

    ``queries`` answer psql calls by a substring of their SQL (checked
    first); ``outputs`` answer by binary name. ``calls`` records every
    command, so tests can prove a secret never reached argv.
    """

    def __init__(self) -> None:
        self.calls: list[Command] = []
        self.outputs: dict[str, CommandOutput] = {
            "systemctl": ok("active\n"),
            "ssh-keyscan": ok("localhost ssh-ed25519 AAAAhostkey\n"),
            "sshd": ok("port 22\npubkeyauthentication yes\n"),
            "psql": ok("postgres\n"),  # password login as postgres
            # A g6e.2xlarge with a 1 TB EBS data volume (NVMe on Nitro).
            "nproc": ok("8\n"),
            "grep": ok("MemTotal:       64815992 kB\n"),  # ~61.8 GiB usable of 64
            "lspci": ok(
                "00:1e.0 3D controller [0302]: NVIDIA Corporation AD102GL [L40S] [10de:26b9]\n"
            ),
            "nvidia-smi": ok("46068\n"),  # MiB — an L40S reports ~45 GiB of its 48 GB
            "findmnt": ok("/dev/nvme1n1p1 1000202273280\n"),
            "lsblk": ok("part \ndisk nvme\n"),
            "tee": ok(""),
            "sed": ok(""),
            # Neo4j's bolt port, on the arcnode gateway only (java's v4-mapped socket)
            "ss": ok("LISTEN 0      4096   [::ffff:172.23.0.1]:7687 *:*\n"),
        }
        self.queries: dict[str, CommandOutput] = {
            # Before "run --rm": the neo4j probe container is a docker run too.
            "neo4j:2026.09.0-community": ok("ok\n1\n"),
            # Before "run --rm": the postgres probe container is a docker run too.
            "inet_client_addr": ok("172.23.0.2\n"),
            "ALTER USER": ok(""),
            "CREATE EXTENSION": ok("CREATE EXTENSION\n"),
            "extname = 'timescaledb'": ok("2.30.2\n"),
            "extname = 'vector'": ok("0.8.0\n"),
            "SHOW listen_addresses": ok("localhost,172.23.0.1\n"),
            "CREATE DATABASE": ok(""),
            "datname LIKE": ok(
                "ems_dercontrol\nems_document\nems_timeseries\nems_vector\n"
            ),
            # docker: the arcnode network + a probe container on it
            "network inspect": ok("172.23.0.0/16 172.23.0.1\n"),
            "network create": ok("4f1c0ffee\n"),
            "run --rm": ok(
                "2: eth0    inet 172.23.0.2/16 brd 172.23.255.255 scope global eth0\n"
            ),
            # cypher-shell --format plain: a header row, then quoted values
            "FROM $old": ok(""),
            "dbms.components": ok('v\n"2026.09.0 community"\n"5 "\n'),
            "SHOW SETTINGS": ok(
                "name, value\n"
                '"server.memory.heap.initial_size", "4.00GiB"\n'
                '"server.memory.heap.max_size", "4.00GiB"\n'
                '"server.memory.pagecache.size", "4.00GiB"\n'
            ),
            "pg_hba_file_rules": ok(
                "127.0.0.1|255.255.255.255\n"
                "::1|ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff\n"
                "172.23.0.0|255.255.0.0\n"
            ),
        }

    def __call__(self, command: Command) -> CommandOutput:
        """The canned output for this command."""
        self.calls.append(command)
        text = " ".join(command.args) + (command.input or "")
        for needle, output in self.queries.items():
            if needle in text:
                return output
        return self.outputs[Path(command.args[0]).name]


def account(tmp_path: Path) -> SshAccount:
    """The installer account, homed under tmp_path, owned by this test user."""
    home = tmp_path / "home" / "joe"
    home.mkdir(parents=True, exist_ok=True)
    return SshAccount(name="joe", home=home, uid=os.getuid(), gid=os.getgid())


def tracker(tmp_path: Path, deployment: Deployment = Deployment.ON_PREM) -> StepTracker:
    """The page-done markers under tmp_path (same dir every call)."""
    return StepTracker(steps_dir=tmp_path / "steps", deployment=deployment)


def make_ssh_service(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    runner: FakeRunner | None = None,
) -> SshService:
    """An SshService on tmp_path with a healthy (or given) fake runner."""
    return SshService(
        account=account(tmp_path),
        deployment=deployment,
        tracker=tracker(tmp_path, deployment),
        run=runner or FakeRunner(),
    )


def make_postgres_service(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    runner: FakeRunner | None = None,
) -> PostgresService:
    """A PostgresService on tmp_path with a healthy (or given) fake runner."""
    return PostgresService(
        deployment=deployment,
        tracker=tracker(tmp_path, deployment),
        secrets_env_path=tmp_path / "secrets.env",
        run=runner or FakeRunner(),
    )


def make_neo4j_service(
    tmp_path: Path,
    deployment: Deployment = Deployment.ON_PREM,
    runner: FakeRunner | None = None,
) -> Neo4jService:
    """A Neo4jService on tmp_path with a healthy (or given) fake runner."""
    return Neo4jService(
        deployment=deployment,
        tracker=tracker(tmp_path, deployment),
        secrets_env_path=tmp_path / "secrets.env",
        run=runner or FakeRunner(),
    )
