"""Pydantic DTOs for the first-boot setup wizard."""

from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
import re

from pydantic import BaseModel, Field, field_validator


class Deployment(StrEnum):
    """Where this box runs — decides who sets up SSH access."""

    CLOUD = "cloud"  # EC2: the key pair chosen at launch already works
    ON_PREM = "on-prem"  # appliance: the wizard creates the key pair


class HardwareMinimums(BaseModel):
    """What the hardware check page enforces, specced like an EC2 instance
    type. Lives in wizard-cfg.yml (setup.sh writes the production values)."""

    vcpus: int
    memory_gib: int
    gpus: int
    gpu_memory_gb: int
    disk_gb: int


class WizardConfig(BaseModel):
    """/etc/arcnode/wizard-cfg.yml, written by the provisioning path."""

    deployment: Deployment
    hardware: HardwareMinimums


class SshAccount(BaseModel):
    """The login account the customer created in the Debian installer —
    their SSH key gets installed for it."""

    name: str
    home: Path
    uid: int
    gid: int


class ApplyRequest(BaseModel):
    """POST /api/ssh body — the public half of the customer's own key
    (``ssh-keygen -y -f private-key.pem``)."""

    ssh_public_key: str = Field(min_length=1)


class Command(BaseModel):
    """A fixed system command. Secrets ride in ``input``/``env``, never argv."""

    args: list[str]
    input: str | None = None
    env: dict[str, str] = {}


class CommandOutput(BaseModel):
    """What a verification probe got back from a system command."""

    returncode: int
    stdout: str


class VerifyCheck(BaseModel):
    """One playbook-style verification row: did it pass, what was seen, and
    the console command that debugs this specific failure."""

    name: str
    ok: bool
    detail: str
    hint: str


class ApplyResult(BaseModel):
    """POST /api/ssh response.

    ``verified`` is the gate: only when every check passes is the wizard
    marked applied. ``account`` lets the UI show the exact ``ssh -i``
    command.
    """

    verified: bool
    account: str
    checks: list[VerifyCheck]


class SetupInfo(BaseModel):
    """GET /api/config — what the UI needs before apply."""

    deployment: Deployment
    account: str
    completed: list[str]


class PasswordRequest(BaseModel):
    """POST /api/postgres, /api/neo4j body — the daemon's admin password.

    Policy: at least 8 characters, one uppercase letter, one digit, one
    special character.
    """

    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_meets_complexity(cls, value: str) -> str:
        """Length is already enforced by the Field constraint above."""
        if not re.search(r"[A-Z]", value):
            raise ValueError("must contain at least one uppercase letter")
        if not re.search(r"\d", value):
            raise ValueError("must contain at least one number")
        if not re.search(r"[^A-Za-z0-9]", value):
            raise ValueError("must contain at least one special character")
        return value


class StepResult(BaseModel):
    """A daemon page's result: ``verified`` is the gate to the next page."""

    verified: bool
    checks: list[VerifyCheck]


class DockerNetwork(BaseModel):
    """The arcnode network as Docker reports it — the range + gateway the
    host daemons trust and listen on. Docker picks them, never us."""

    subnet: IPv4Network
    gateway: IPv4Address
