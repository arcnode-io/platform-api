"""The on-prem HTTPS certificate page, optional. The box makes a key and a
signing request for its name on the customer's network; their IT signs it with
their own certificate authority; the box installs what comes back and serves
the HMI over HTTPS on 443. Nothing here contacts ArcNode, and http://<ip>/
keeps working either way.

IT can also do it by hand: the certificate chain goes in /opt/arcnode/tls/server.pem,
its key in /opt/arcnode/tls/server-key.pem, then
`sudo docker compose -f /opt/arcnode/docker-compose.yaml -f /opt/arcnode/docker-compose.onprem.yaml up -d https-ingress`.
"""

from pathlib import Path
from typing import Final

from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    HttpsCertificate,
    SigningRequest,
    SigningRequestResult,
    StepResult,
    VerifyCheck,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

HTTPS_SERVICE: Final[str] = "https-ingress"
DER_INGRESS_SERVICE: Final[str] = "der-control-ingress"
# Same file the cloud's UserData fetches from arcnode-public.
CONFIG_URL: Final[str] = (
    "https://arcnode-public.s3.us-east-1.amazonaws.com/compose/https-ingress.conf"
)
CONFIG_FILE: Final[str] = "https-ingress.conf"
TLS_DIR: Final[str] = "tls"
DER_TLS_DIR: Final[str] = "der-control-tls"
PENDING_KEY: Final[str] = "pending-key.pem"
PENDING_HOST: Final[str] = "pending-host"
READY_LINE: Final[str] = "start worker processes"
MATCH_CHECK: Final[str] = "Certificate matches the key made on this box"
LOG_HINT: Final[str] = (
    f"sudo docker compose -f /opt/arcnode/docker-compose.yaml logs {HTTPS_SERVICE}"
)


class HttpsService:
    """Signing request out, signed certificate in, HTTPS front end started."""

    def __init__(self, *, tracker: StepTracker, ems_dir: Path, run: Runner) -> None:
        self._tracker = tracker
        self._ems_dir = ems_dir
        self._run = run

    def request_signing(self, request: SigningRequest) -> SigningRequestResult:
        """Make the box's key (it never leaves) and a signing request for its name."""
        tls = self._ems_dir / TLS_DIR
        tls.mkdir(parents=True, exist_ok=True)
        key = tls / PENDING_KEY
        out = self._openssl(
            "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-keyout", str(key), "-subj", f"/CN={request.hostname}",
            "-addext", f"subjectAltName=DNS:{request.hostname}",
        )  # fmt: skip
        key.chmod(0o600)
        (tls / PENDING_HOST).write_text(request.hostname)
        return SigningRequestResult(csr_pem=out)

    def apply(self, request: HttpsCertificate) -> StepResult:
        """Check the certificate against the key and the name, install it, start
        the front end, and prove it serves this certificate."""
        if self._tracker.is_done("https"):
            raise StepAlreadyDoneError("HTTPS is already set up")
        tls = self._ems_dir / TLS_DIR
        host = (tls / PENDING_HOST).read_text()
        leaf = _first_certificate(request.certificate_pem)
        checks = [
            self._match_check(leaf, tls / PENDING_KEY),
            self._name_check(leaf, host),
        ]
        if not all(check.ok for check in checks):
            return StepResult(verified=False, checks=checks)
        self._install(request.certificate_pem, tls / PENDING_KEY)
        self._run(
            Command(
                args=[
                    "curl",
                    "-fsSL",
                    CONFIG_URL,
                    "-o",
                    str(self._ems_dir / CONFIG_FILE),
                ]
            )
        )
        self._run(
            compose_command(
                self._ems_dir, "up", "-d", "--force-recreate", HTTPS_SERVICE
            )
        )
        wait_for_log(self._run, self._ems_dir, HTTPS_SERVICE, READY_LINE)
        self._reload_der_ingress()
        checks += [self._running_check(), self._served_check(leaf, host)]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("https")
        return StepResult(verified=verified, checks=checks)

    def skip(self) -> StepResult:
        """Keep plain http://<ip>/; IT can install a certificate later by hand."""
        self._tracker.mark_done("https")
        return StepResult(
            verified=True,
            checks=[
                VerifyCheck(
                    name="Skipped for now",
                    ok=True,
                    detail="the HMI stays on http://<this box's address>/",
                    hint="",
                )
            ],
        )

    def _openssl(self, *args: str, stdin: str | None = None) -> str:
        out = self._run(Command(args=["openssl", *args], input=stdin))
        if out.returncode != 0:
            raise RuntimeError(f"openssl {args[0]} failed: {out.stdout}")
        return out.stdout

    def _match_check(self, leaf: str, key: Path) -> VerifyCheck:
        cert_key = self._openssl("x509", "-noout", "-pubkey", stdin=leaf)
        box_key = self._openssl("pkey", "-pubout", "-in", str(key))
        matches = cert_key == box_key
        return VerifyCheck(
            name=MATCH_CHECK,
            ok=matches,
            detail=(
                "signed from this box's request"
                if matches
                else "signed for a different key — give IT the request from this page"
            ),
            hint="",
        )

    def _name_check(self, leaf: str, host: str) -> VerifyCheck:
        # Reason: -checkhost exits non-zero on a mismatch; that's the answer, not a failure.
        out = self._run(
            Command(args=["openssl", "x509", "-noout", "-checkhost", host], input=leaf)
        ).stdout
        issued = "does match" in out
        return VerifyCheck(
            name=f"Issued for {host}",
            ok=issued,
            detail=out.strip(),
            hint="ask IT to put the name in the certificate's Subject Alternative Name",
        )

    def _install(self, chain: str, pending_key: Path) -> None:
        """The HMI's front end and the utility-facing DER ingress serve the same certificate."""
        key = pending_key.read_text()
        for directory, cert_name, key_name in (
            (TLS_DIR, "server.pem", "server-key.pem"),
            (DER_TLS_DIR, "cert.pem", "key.pem"),
        ):
            target = self._ems_dir / directory
            target.mkdir(parents=True, exist_ok=True)
            (target / cert_name).write_text(chain)
            key_path = target / key_name
            key_path.touch(mode=0o600)
            key_path.chmod(0o600)
            key_path.write_text(key)
        pending_key.unlink()

    def _reload_der_ingress(self) -> None:
        """A running DER ingress picks up the new certificate; one that isn't running reads it at start."""
        running = self._run(
            compose_command(
                self._ems_dir, "ps", "-q", "--status", "running", DER_INGRESS_SERVICE
            )
        ).stdout.strip()
        if running:
            self._run(
                compose_command(
                    self._ems_dir, "exec", DER_INGRESS_SERVICE, "nginx", "-s", "reload"
                )
            )

    def _running_check(self) -> VerifyCheck:
        out = self._run(
            compose_command(
                self._ems_dir, "ps", "-q", "--status", "running", HTTPS_SERVICE
            )
        )
        running = bool(out.stdout.strip())
        return VerifyCheck(
            name="HTTPS front end running",
            ok=running,
            detail="listening on 443" if running else "not running",
            hint=LOG_HINT,
        )

    def _served_check(self, leaf: str, host: str) -> VerifyCheck:
        out = self._run(
            Command(
                args=[
                    "openssl",
                    "s_client",
                    "-connect",
                    "127.0.0.1:443",
                    "-servername",
                    host,
                ],
                input="",
            )
        )
        served = leaf.strip() in out.stdout
        return VerifyCheck(
            name=f"https://{host} serves this certificate",
            ok=served,
            detail="served on 443" if served else "443 serves a different certificate",
            hint=f"openssl s_client -connect 127.0.0.1:443 -servername {host}",
        )


def _first_certificate(chain: str) -> str:
    """The leaf: the first PEM block of the chain IT sent back."""
    end = "-----END CERTIFICATE-----"
    return chain.split(end)[0].strip() + f"\n{end}\n"
