"""Pydantic DTOs for the first-boot setup wizard."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
import re

from pydantic import model_validator, BaseModel, Field, field_validator


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


class WizardConfig(BaseModel):
    """/etc/arcnode/wizard-cfg.yml, written by setup.sh."""

    hardware: HardwareMinimums
    ollama: OllamaSettings


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


class TelemetryRequest(BaseModel):
    """POST /api/telemetry body — how many days of measurements to keep."""

    retention_days: int = Field(ge=1)


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
    """POST /api/hivemq body — the customer's three passwords. The four service
    accounts share `service`; operator and viewer are people, and each one's
    password is both their HMI login and their broker account (one password per
    role). Nothing is generated (customer-sets-all-secrets)."""

    service: str = Field(min_length=8)
    operator: str = Field(min_length=8)
    viewer: str = Field(min_length=8)

    @field_validator("service", "operator", "viewer")
    @classmethod
    def password_meets_complexity(cls, value: str) -> str:
        """Same policy as the daemon passwords."""
        return check_complexity(value)


class DerControlRequest(BaseModel):
    """POST /api/der-control body — the DERMS base URL the customer's utility
    gives. Optional: blank means the utility isn't connected yet."""

    utility_mirror_url: str | None = None
    lfdi_allowlist: str = (
        ""  # the DERMS certificate's LFDIs; empty refuses every DER control
    )
    device_cert_pem: str = (
        ""  # the box's client certificate, as the utility registered it
    )
    device_key_pem: str = ""  # its private key; cert and key go together or not at all
    utility_ca_pem: str = ""  # the CA bundle that verifies the utility's server

    @field_validator("utility_mirror_url")
    @classmethod
    def must_be_https(cls, value: str | None) -> str | None:
        """The utility's endpoint is reached over TLS, same as the ingress."""
        if value is not None and not value.startswith("https://"):
            raise ValueError("must be an https:// URL")
        return value

    @model_validator(mode="after")
    def utility_identity_is_well_formed(self) -> "DerControlRequest":
        """A half identity, a non-PKCS#8 key, or a non-PEM file would fail der-control-api at boot."""
        if bool(self.device_cert_pem) != bool(self.device_key_pem):
            raise ValueError(
                "the device certificate and its private key must be given together"
            )
        if (
            self.device_cert_pem
            and "-----BEGIN CERTIFICATE-----" not in self.device_cert_pem
        ):
            raise ValueError(
                "the device certificate must be PEM (-----BEGIN CERTIFICATE-----)"
            )
        if (
            self.device_key_pem
            and "-----BEGIN PRIVATE KEY-----" not in self.device_key_pem
        ):
            raise ValueError(
                "the device key must be PKCS#8 PEM (-----BEGIN PRIVATE KEY-----)"
            )
        if (
            self.utility_ca_pem
            and "-----BEGIN CERTIFICATE-----" not in self.utility_ca_pem
        ):
            raise ValueError("the utility CA bundle must be PEM certificates")
        return self

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
    """POST /api/device-api body — the key the Device API signs sessions with.
    The operator and viewer passwords it checks logins against were set on the
    HiveMQ page (one password per role)."""

    jwt_secret: str = Field(min_length=32)


class SshLockdownRequest(BaseModel):
    """The last page: key-only SSH. Checked by default; unchecking is allowed."""

    disable_password_login: bool = True


class SiteInfo(BaseModel):
    """The Site page's read-only rows, from the order the configurator baked in.
    None where the order doesn't carry the field (older orders)."""

    customer: str | None
    site: str
    market: str | None
    order_id: str | None
