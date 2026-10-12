"""The on-prem HMI page: write the box's TLS cert, start the operator screen and
the HTTPS ingress in front of it, verify both answer. Nothing to type."""

from pathlib import Path
from typing import Final

from src.wizard.box_address import box_address
from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

HMI_SERVICE: Final[str] = "hmi"
INGRESS_SERVICE: Final[str] = "https-ingress"
# nginx logs this once its workers are up (both the HMI and the ingress run nginx).
READY_LINE: Final[str] = "start worker processes"
PROBE_IMAGE: Final[str] = "curlimages/curl"
HMI_URL: Final[str] = "http://hmi/"
# Where the ingress mounts the cert (src/compose/https-ingress.conf).
TLS_DIR: Final[str] = "tls"
CERT_FILE: Final[str] = "server.pem"
KEY_FILE: Final[str] = "server-key.pem"
CERT_DAYS: Final[str] = "3650"
HTTP_URL: Final[str] = "http://127.0.0.1/"
LOG_HINT: Final[str] = (
    "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs hmi https-ingress"
)


class HmiStepNotAvailableError(Exception):
    """No HMI page in the cloud — UserData starts it there."""


class HmiService:
    """Starts the operator screen that the box's browsers open, over HTTPS."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        ems_dir: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._run = run

    def apply(self) -> StepResult:
        """Write the cert, start, wait for both nginx, verify — done only when every check passes."""
        if self._deployment == Deployment.CLOUD:
            raise HmiStepNotAvailableError("no HMI page in the cloud")
        if self._tracker.is_done("hmi"):
            raise StepAlreadyDoneError("HMI is already set up")
        self._run(
            compose_command(self._ems_dir, "up", "-d", HMI_SERVICE, INGRESS_SERVICE)
        )
        wait_for_log(self._run, self._ems_dir, HMI_SERVICE, READY_LINE)
        wait_for_log(self._run, self._ems_dir, INGRESS_SERVICE, READY_LINE)
        checks = [self._serves_app(), self._serves_http()]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("hmi")
        return StepResult(verified=verified, checks=checks)

    def _write_self_signed_cert(self) -> None:
        """A self-signed cert for the box's address, kept across reruns of the page."""
        tls_dir = self._ems_dir / TLS_DIR
        tls_dir.mkdir(parents=True, exist_ok=True)
        cert, key = tls_dir / CERT_FILE, tls_dir / KEY_FILE
        if cert.exists():
            return
        # Reason: openssl keeps an existing file's mode, so create the key 0600 first.
        key.touch(mode=0o600)
        key.chmod(0o600)
        address = box_address(self._run)
        self._run(
            Command(
                args=[
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    CERT_DAYS,
                    "-subj",
                    f"/CN={address}",
                    "-addext",
                    f"subjectAltName=IP:{address}",
                ]
            )
        )

    def _serves_app(self) -> VerifyCheck:
        out = self._run(
            Command(
                args=[
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    DOCKER_NETWORK,
                    PROBE_IMAGE,
                    "-fsS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    HMI_URL,
                ]
            )
        )
        ok = out.returncode == 0 and out.stdout.strip() == "200"
        return VerifyCheck(
            name="Serves the operator screen",
            ok=ok,
            detail=(
                "HTTP 200 on port 80"
                if ok
                else f"got {out.stdout.strip() or f'exit {out.returncode}'}"
            ),
            hint=LOG_HINT,
        )

    def _serves_http(self) -> VerifyCheck:
        """From the host, through the published port: what a browser on the LAN gets."""
        out = self._run(
            Command(
                args=[
                    "curl",
                    "-fsS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    HTTP_URL,
                ]
            )
        )
        ok = out.returncode == 0 and out.stdout.strip() == "200"
        return VerifyCheck(
            name="Serves HTTP on port 80",
            ok=ok,
            detail=(
                "HTTPS 200 on port 80"
                if ok
                else f"got {out.stdout.strip() or f'exit {out.returncode}'}"
            ),
            hint=LOG_HINT,
        )
