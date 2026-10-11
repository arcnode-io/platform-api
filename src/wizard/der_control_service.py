"""The on-prem DER control API page: write its per-site overlay (the order's
site, the box's address for the utility, and the DERMS URL if the customer
gives one), start the service, verify its health. The DER ingress in front of
it is a separate page."""

import base64
import hashlib
import re
from pathlib import Path
from typing import Final

import yaml

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.ems_cfg import DER_CONTROL_CFG_FILE, DerControlCfg, write_yaml
from src.wizard.order_record import SITE_FILE, OrderSite
from src.wizard.secrets_env import save_secrets
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, DerControlRequest, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

DER_CONTROL_SERVICE: Final[str] = "der-control-api"
LFDI_ALLOWLIST_NAME: Final[str] = "DER_CONTROL_LFDI_ALLOWLIST"
IDENTITY_CHECK: Final[str] = "Utility identity loaded"
# The utility identity files; der-control-api mounts these read-only at /app/tls/utility/.
CLIENT_CERT_FILE: Final[str] = "der-control-client.pem"
CLIENT_KEY_FILE: Final[str] = "der-control-client-key.pem"
UTILITY_CA_FILE: Final[str] = "der-control-utility-ca.pem"
# Spring Boot prints this once the app has started, whatever the allowlist holds.
# (An empty allowlist logs a WARN instead of the LFDI count, so waiting on that line hangs.)
READY_LINE: Final[str] = "Started Application in"
HEALTH_URL: Final[str] = "http://der-control-api:8080/actuator/health"
PROBE_IMAGE: Final[str] = "curlimages/curl"
# The DER ingress's public port on the box; the utility reaches it there.
INGRESS_PORT: Final[int] = 8443
ROUTE_COMMAND: Final[list[str]] = ["ip", "-4", "route", "get", "1.1.1.1"]
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs der-control-api"
SOURCE_ADDRESS: Final[re.Pattern[str]] = re.compile(r"\bsrc (\S+)")


class DerControlStepNotAvailableError(Exception):
    """No DER control API page in the cloud — UserData writes its overlay there."""


class DerControlService:
    """Writes der-control-api's per-site overlay and starts the service."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        order_dir: Path,
        ems_dir: Path,
        secrets_env_path: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._order_dir = order_dir
        self._secrets_env_path = secrets_env_path
        self._ems_dir = ems_dir
        self._run = run

    def apply(self, request: DerControlRequest) -> StepResult:
        """Write the overlay, start, wait for the allowlist line, verify health — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise DerControlStepNotAvailableError("no DER control API page in the cloud")
        if self._tracker.is_done("der_control_api"):
            raise StepAlreadyDoneError("the DER control API is already set up")
        site = OrderSite.model_validate(yaml.safe_load((self._order_dir / SITE_FILE).read_text()))
        expected = DerControlCfg(
            site_id=site.site_id,
            public_base_url=f"https://{self._box_address()}:{INGRESS_PORT}",
            utility_mirror_url=request.utility_mirror_url,
        )
        write_yaml(self._ems_dir / DER_CONTROL_CFG_FILE, expected)
        # Reason: the allowlist is read once at boot, so the container is recreated to pick it up.
        save_secrets(self._secrets_env_path, {LFDI_ALLOWLIST_NAME: request.lfdi_allowlist})
        self._write_utility_identity(request)
        self._run(compose_command(self._ems_dir, "up", "-d", "--force-recreate", DER_CONTROL_SERVICE))
        wait_for_log(self._run, self._ems_dir, DER_CONTROL_SERVICE, READY_LINE)
        checks = [self._running_check(), self._health_check(), self._saved_check(expected)]
        if request.device_cert_pem:
            checks.append(self._identity_check(request.device_cert_pem))
        # Reason: the utility identity is informational. A customer without it finishes setup, and a
        # mismatch shows on the page without holding Continue.
        verified = all(check.ok for check in checks if check.name != IDENTITY_CHECK)
        if verified:
            self._tracker.mark_done("der_control_api")
        return StepResult(verified=verified, checks=checks)

    def _write_utility_identity(self, request: DerControlRequest) -> None:
        """Write the utility files der-control-api mounts, or remove them when none are given."""
        files = {
            CLIENT_CERT_FILE: (request.device_cert_pem, 0o644),
            CLIENT_KEY_FILE: (request.device_key_pem, 0o600),
            UTILITY_CA_FILE: (request.utility_ca_pem, 0o644),
        }
        for name, (content, mode) in files.items():
            path = self._ems_dir / name
            if not content:
                path.unlink(missing_ok=True)
                continue
            path.touch(mode=mode)
            path.chmod(mode)
            path.write_text(content)

    def skip(self) -> StepResult:
        """Mark the page done without starting the service: the utility isn't connected yet.
        The customer adds the link later, so nothing here can block the rest of setup."""
        if self._deployment == Deployment.CLOUD:
            raise DerControlStepNotAvailableError("no DER control API page in the cloud")
        self._tracker.mark_done("der_control_api")
        return StepResult(
            verified=True,
            checks=[VerifyCheck(name="Skipped for now", ok=True, detail="add the utility link later", hint="")],
        )

    def _box_address(self) -> str:
        """The address the box uses to reach the internet — the one the utility sees."""
        out = self._run(Command(args=ROUTE_COMMAND))
        match = SOURCE_ADDRESS.search(out.stdout)
        if match is None:
            raise RuntimeError(f"no source address in: {out.stdout!r}")
        return match.group(1)

    def _identity_check(self, cert_pem: str) -> VerifyCheck:
        """The LFDI the utility must register, and whether der-control-api loaded that same identity."""
        lfdi = lfdi_from_cert_pem(cert_pem)
        logs = self._run(compose_command(self._ems_dir, "logs", DER_CONTROL_SERVICE)).stdout
        loaded = f"utility TLS identity loaded from /app/tls/utility: LFDI {lfdi}" in logs
        return VerifyCheck(
            name=IDENTITY_CHECK,
            ok=loaded,
            detail=f"LFDI {lfdi}" if loaded else f"register LFDI {lfdi} with the utility; not loaded yet",
            hint=LOG_HINT,
        )

    def _running_check(self) -> VerifyCheck:
        out = self._run(compose_command(self._ems_dir, "ps", "-q", "--status", "running", DER_CONTROL_SERVICE))
        running = bool(out.stdout.strip())
        return VerifyCheck(
            name="DER control API running",
            ok=running,
            detail="running" if running else "not running",
            hint=LOG_HINT,
        )

    def _health_check(self) -> VerifyCheck:
        out = self._run(
            Command(args=["docker", "run", "--rm", "--network", DOCKER_NETWORK, PROBE_IMAGE, "-fsS", HEALTH_URL])
        )
        ok = out.returncode == 0 and '"status":"UP"' in out.stdout.replace(" ", "")
        return VerifyCheck(
            name="DER control API healthy",
            ok=ok,
            detail="actuator reports UP" if ok else f"health not UP (curl exit {out.returncode})",
            hint=LOG_HINT,
        )

    def _saved_check(self, expected: DerControlCfg) -> VerifyCheck:
        """Read the overlay back — what the container will actually mount."""
        path = self._ems_dir / DER_CONTROL_CFG_FILE
        saved = DerControlCfg.model_validate(yaml.safe_load(path.read_text())) == expected
        return VerifyCheck(
            name="Saved for the DER control API",
            ok=saved,
            detail=str(path) if saved else "missing or different",
            hint=f"sudo cat {path}",
        )


def lfdi_from_cert_pem(pem: str) -> str:
    """The LFDI for a certificate: the first 20 bytes of its DER SHA-256, as 40 hex characters."""
    body = "".join(
        line for line in pem.splitlines() if line and not line.startswith("-----")
    )
    der = base64.b64decode(body)
    return hashlib.sha256(der).hexdigest()[:40]
