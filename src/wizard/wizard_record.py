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
    disk_nvme: bool  # production: true; test-mode.sh allows SATA


class OllamaSettings(BaseModel):
    """wizard-cfg.yml's ``ollama:`` block — the models the Ollama page pulls
    and the chat context it serves (test-mode.sh swaps in tiny ones)."""

    chat_model: str
    embedding_model: str
    context_length: int


class Variant(StrEnum):
    """Which cloud product this box is: commercial or defense. Only cloud has one."""

    COMMERCIAL = "commercial"
    DEFENSE = "defense"


class Badge(StrEnum):
    """The label in the wizard header: where the box runs and which product it is."""

    ON_PREM = "🖥️ On-Prem"
    COMMERCIAL = "☁️ Commercial"
    DEFENSE = "🛡️ Defense"


def badge_for(deployment: Deployment, variant: Variant) -> Badge:
    """On-prem is always On-Prem; cloud is Commercial or Defense by variant."""
    if deployment == Deployment.ON_PREM:
        return Badge.ON_PREM
    return Badge.DEFENSE if variant == Variant.DEFENSE else Badge.COMMERCIAL


class WizardConfig(BaseModel):
    """/etc/arcnode/wizard-cfg.yml, written by the provisioning path."""

    deployment: Deployment
    variant: Variant = Variant.COMMERCIAL  # cloud only; on-prem ignores it
    hardware: HardwareMinimums
    ollama: OllamaSettings | None = None  # on-prem only


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
    badge: Badge
    account: str
    completed: list[str]


def check_complexity(value: str) -> str:
    """The daemon password policy: an uppercase letter, a number, a special character."""
    if not re.search(r"[A-Z]", value):
        raise ValueError("must contain at least one uppercase letter")
    if not re.search(r"\d", value):
        raise ValueError("must contain at least one number")
    if not re.search(r"[^A-Za-z0-9]", value):
        raise ValueError("must contain at least one special character")
    return value


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
        return check_complexity(value)


class StepResult(BaseModel):
    """A daemon page's result: ``verified`` is the gate to the next page."""

    verified: bool
    checks: list[VerifyCheck]


class DockerNetwork(BaseModel):
    """The arcnode network as Docker reports it — the range + gateway the
    host daemons trust and listen on. Docker picks them, never us."""

    subnet: IPv4Network
    gateway: IPv4Address


class BrokerPasswords(BaseModel):
    """POST /api/hivemq body — the customer's three broker passwords. The four
    service accounts share `service`; operator and viewer are people. Nothing
    is generated (customer-sets-all-secrets)."""

    service: str = Field(min_length=8)
    operator: str = Field(min_length=8)
    viewer: str = Field(min_length=8)

    @field_validator("service", "operator", "viewer")
    @classmethod
    def password_meets_complexity(cls, value: str) -> str:
        """Same policy as the daemon passwords."""
        return check_complexity(value)


class CloudSecrets(BaseModel):
    """POST /api/cloud-secrets body — the three passwords the cloud customer sets,
    the same ones the on-prem box asks for on its own pages."""

    operator_password: str = Field(min_length=8)
    viewer_password: str = Field(min_length=8)
    grafana_password: str = Field(min_length=8)

    @field_validator("operator_password", "viewer_password", "grafana_password")
    @classmethod
    def password_meets_complexity(cls, value: str) -> str:
        """Same policy as the daemon passwords."""
        return check_complexity(value)


class DerControlRequest(BaseModel):
    """POST /api/der-control body — the DERMS base URL the customer's utility
    gives. Optional: blank means the utility isn't connected yet."""

    utility_mirror_url: str | None = None
    lfdi_allowlist: str = ""  # the DERMS certificate's LFDIs; empty refuses every DER control

    @field_validator("utility_mirror_url")
    @classmethod
    def must_be_https(cls, value: str | None) -> str | None:
        """The utility's endpoint is reached over TLS, same as the ingress."""
        if value is not None and not value.startswith("https://"):
            raise ValueError("must be an https:// URL")
        return value

    @field_validator("lfdi_allowlist")
    @classmethod
    def lfdis_are_40_hex(cls, value: str) -> str:
        """Comma, space, or newline separated; each id is 40 hex characters. Stored lowercase, space separated."""
        ids = [part for part in re.split(r"[,\s]+", value) if part]
        for lfdi in ids:
            if not re.fullmatch(r"[0-9a-fA-F]{40}", lfdi):
                raise ValueError(f"not a 40-character hex LFDI: {lfdi!r}")
        return " ".join(lfdi.lower() for lfdi in ids)


class AnalystServerKeys(BaseModel):
    """POST /api/analyst-server body — the two API keys the analyst's weather
    and market tools call out with. The customer sets both."""

    openweathermap_api_key: str = Field(min_length=8)
    gridstatus_api_key: str = Field(min_length=8)


class DeviceApiSecrets(BaseModel):
    """POST /api/device-api body — the auth secrets the Device API signs and
    checks logins with. The customer sets all three."""

    jwt_secret: str = Field(min_length=32)
    operator_password: str = Field(min_length=8)
    viewer_password: str = Field(min_length=8)

    @field_validator("operator_password", "viewer_password")
    @classmethod
    def password_meets_complexity(cls, value: str) -> str:
        """Same policy as the daemon passwords."""
        return check_complexity(value)
