"""WizardService — the first-boot setup wizard's real backend logic.

Runs as its own standalone FastAPI app (src/wizard/main.py), baked into
both the appliance ISO (fetched + started by late_command) and the cloud
AMI (started by EC2 UserData) — not mounted into platform-api's own
running service. See src/wizard/README.md for why.

Writes plaintext to secrets.env deliberately — same established pattern
as auth_secrets.py's AuthOperatorPw/AuthViewerPw (device-api bcrypt-hashes
at boot; this process never stores a hash itself, it just hands off the
same plaintext-in-env-file shape device-api already expects).
"""

import logging
import shutil
import subprocess  # nosec B404 — openssl invocation below, absolute path, no shell
from pathlib import Path
from typing import Final

from src.wizard.wizard_record import ApplyRequest, ApplyResult

# env var names — must match COMMON_URL_SLOTS / AUTH_SLOTS in
# src/cfn/cfn_resources.py exactly, since device-api / analyst-agent read
# these names regardless of which delivery path (cloud UserData, on-prem
# late_command+wizard) populated secrets.env.
_API_KEY_ENV_NAMES: Final[dict[str, str]] = {
    "openweathermap": "OPENWEATHERMAP_API_KEY",
    "gridstatus": "GRIDSTATUS_API_KEY",
}
_OPENSSL_CERT_DAYS: Final[str] = "3650"
_OPENSSL_KEY_BITS: Final[str] = "2048"

logger = logging.getLogger(__name__)


class WizardAlreadyAppliedError(Exception):
    """Raised when /api/apply is called a second time.

    The wizard runs once; its whole premise (per the mockup: "/setup
    disappears after apply") is that a second call never happens through
    the normal UI, but the API itself must refuse it too — not just hide
    the button.
    """


class WizardService:
    """Collects wizard input, writes it to the files the real stack reads.

    Constructor takes paths, not hardcoded locations — same
    dependency-injection-for-testability convention as the rest of this
    repo (e.g. PersistenceService's lambda_runtime/psycopg2_layer_arn_template).
    """

    def __init__(
        self,
        *,
        secrets_env_path: Path,
        tls_cert_path: Path,
        tls_key_path: Path,
        applied_marker_path: Path,
    ) -> None:
        self._secrets_env_path = secrets_env_path
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._applied_marker_path = applied_marker_path

    def is_applied(self) -> bool:
        """True once apply() has succeeded — the wizard is done, the
        /setup route should 404 from here on."""
        return self._applied_marker_path.exists()

    def apply(self, request: ApplyRequest) -> ApplyResult:
        """Write secrets.env + TLS assets, then mark applied.

        Raises WizardAlreadyAppliedError if called a second time —
        idempotent guard matches the arcnode-hmi-docker.service pattern
        (docker inspect) used everywhere else in this appliance's
        provisioning: the guard lives at the point of the irreversible
        action, not just in the UI.
        """
        if self.is_applied():
            raise WizardAlreadyAppliedError(
                "setup has already been applied on this install"
            )

        self._write_secrets_env(request)
        self._write_tls(request)
        self._applied_marker_path.parent.mkdir(parents=True, exist_ok=True)
        self._applied_marker_path.touch()

        return ApplyResult(success=True, message="Setup applied.")

    def _write_secrets_env(self, request: ApplyRequest) -> None:
        lines: list[str] = []
        for key_id, env_name in _API_KEY_ENV_NAMES.items():
            value = request.api_keys.get(key_id)
            if value is not None and not value.skipped and value.key:
                lines.append(f"{env_name}={value.key}")
        lines.append(f"AUTH_OPERATOR_PW={request.human_auth.operator_password}")
        lines.append(f"AUTH_VIEWER_PW={request.human_auth.viewer_password}")

        self._secrets_env_path.parent.mkdir(parents=True, exist_ok=True)
        self._secrets_env_path.write_text("\n".join(lines) + "\n")
        self._secrets_env_path.chmod(0o600)

    def _write_tls(self, request: ApplyRequest) -> None:
        self._tls_cert_path.parent.mkdir(parents=True, exist_ok=True)
        self._tls_key_path.parent.mkdir(parents=True, exist_ok=True)

        if request.tls.mode == "upload":
            # Validated non-empty by TlsInput's own model_validator already.
            assert request.tls.cert_pem is not None
            assert request.tls.key_pem is not None
            self._tls_cert_path.write_text(request.tls.cert_pem)
            self._tls_key_path.write_text(request.tls.key_pem)
        else:
            self._generate_selfsigned_cert()
        self._tls_key_path.chmod(0o600)

    def _generate_selfsigned_cert(self) -> None:
        """Same openssl shape as cfn_resources.py's der_control_ingress
        block — one proven pattern, not a new one."""
        openssl_path = shutil.which("openssl")
        if openssl_path is None:
            raise RuntimeError("openssl not found on PATH")
        # Resolved absolute path, no shell, every other arg is a hardcoded
        # constant or a Path this process generated itself.
        subprocess.run(  # noqa: S603  # nosec B603
            [
                openssl_path,
                "req",
                "-x509",
                "-newkey",
                f"rsa:{_OPENSSL_KEY_BITS}",
                "-nodes",
                "-keyout",
                str(self._tls_key_path),
                "-out",
                str(self._tls_cert_path),
                "-days",
                _OPENSSL_CERT_DAYS,
                "-subj",
                "/CN=arcnode-appliance",
            ],
            check=True,
            capture_output=True,
        )
