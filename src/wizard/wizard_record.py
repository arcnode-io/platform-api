"""Pydantic DTOs for the first-boot setup wizard's apply request/result."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

MIN_HUMAN_PASSWORD_LENGTH = 12


class ApiKeyInput(BaseModel):
    """One third-party integration's wizard-collected value.

    ``skipped`` disables the integration rather than leaving it misconfigured
    — markets.py's labelled-synthetic-data fallback (GridStatus) or the
    forecast tool going historicals-only (OpenWeatherMap) depend on the key
    being genuinely absent from the environment, not set to an empty string.
    """

    key: str = ""
    skipped: bool = False


class TlsInput(BaseModel):
    """Self-signed (generated here) or customer-uploaded cert + key.

    Let's Encrypt isn't modeled yet — real ACME client integration is its
    own scope, deferred; see src/wizard/README.md.
    """

    mode: Literal["selfsigned", "upload"]
    cert_pem: Optional[str] = None
    key_pem: Optional[str] = None

    @model_validator(mode="after")
    def upload_requires_both_pem_fields(self) -> "TlsInput":
        """Refuse a half-uploaded cert — a cert with no key (or vice versa) is unusable."""
        if self.mode == "upload" and (not self.cert_pem or not self.key_pem):
            raise ValueError("upload mode requires both cert_pem and key_pem")
        return self


class HumanAuthInput(BaseModel):
    """First operator + viewer login passwords.

    Matches the real, already-established model exactly (auth_secrets.py:
    AUTH_OPERATOR_PW / AUTH_VIEWER_PW, device-api bcrypt-hashes these at
    boot from secrets.env plaintext) — not the wizard mockup's single
    "admin" user, which doesn't match what device-api actually expects.
    Two fixed roles, no customizable username.
    """

    operator_password: str = Field(min_length=MIN_HUMAN_PASSWORD_LENGTH)
    operator_confirm: str
    viewer_password: str = Field(min_length=MIN_HUMAN_PASSWORD_LENGTH)
    viewer_confirm: str

    @model_validator(mode="after")
    def passwords_match(self) -> "HumanAuthInput":
        """Catch a typo'd confirm field before it locks an operator out."""
        if self.operator_password != self.operator_confirm:
            raise ValueError("operator password and confirm do not match")
        if self.viewer_password != self.viewer_confirm:
            raise ValueError("viewer password and confirm do not match")
        return self


class ApplyRequest(BaseModel):
    """POST /api/apply body — everything the wizard collected."""

    api_keys: dict[str, ApiKeyInput]
    tls: TlsInput
    human_auth: HumanAuthInput


class ApplyResult(BaseModel):
    """POST /api/apply response."""

    success: bool
    message: str


class InstallIdentity(BaseModel):
    """Step 1's read-only display — confirms the right build landed at the
    right site. Mirrors the old iso_bake_service's install.json shape
    (customer/site/market/isoVersion/orderId), read from a file written at
    ISO-build or AMI-launch time, not collected by the wizard itself.
    """

    customer: str
    site: str
    market: str
    iso_version: str
    order_id: str
