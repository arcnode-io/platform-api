"""Pydantic DTOs for the first-boot setup wizard."""

from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, Field


class Deployment(StrEnum):
    """Where this box runs — decides who sets up SSH access."""

    CLOUD = "cloud"  # EC2: the key pair chosen at launch already works
    ON_PREM = "on-prem"  # appliance: the wizard creates the key pair


class WizardConfig(BaseModel):
    """/etc/arcnode/wizard-cfg.yml, written by the provisioning path."""

    deployment: Deployment


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
