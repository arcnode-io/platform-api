"""The on-prem DER ingress: the mutual-TLS front door on 8443 the utility posts
DER events to. IEEE 2030.5 requires client certificates, so it only lets in a
client whose certificate the utility's CA signed, then forwards to der-control-api.

It serves a self-signed certificate for the box's address until the HTTPS page
installs the customer's own; a certificate already there is kept."""

from pathlib import Path
from typing import Final

from src.der_control_truststore import PLACEHOLDER_TRUSTSTORE_PEM
from src.wizard.containers_compose import compose_command, wait_for_log
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, VerifyCheck

DER_INGRESS_SERVICE: Final[str] = "der-control-ingress"
TLS_DIR: Final[str] = "der-control-tls"
# Same file the cloud's UserData fetches from arcnode-public.
CONFIG_URL: Final[str] = (
    "https://arcnode-public.s3.us-east-1.amazonaws.com/der-control-ingress/nginx.conf"
)
CONFIG_FILE: Final[str] = "der-control-ingress.conf"
READY_LINE: Final[str] = "start worker processes"


def start_der_ingress(
    run: Runner, ems_dir: Path, address: str, utility_ca_pem: str
) -> VerifyCheck:
    """Write the ingress's certificate (if none yet) and truststore, start it, check it runs.

    An empty utility CA gets a placeholder that trusts nothing, so every client is refused.
    """
    tls = ems_dir / TLS_DIR
    tls.mkdir(parents=True, exist_ok=True)
    if not (tls / "cert.pem").exists():
        run(
            Command(
                args=[
                    "openssl", "req", "-x509", "-newkey", "ec",
                    "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-keyout", str(tls / "key.pem"), "-out", str(tls / "cert.pem"),
                    "-days", "3650", "-subj", f"/CN={address}",
                    "-addext", f"subjectAltName=IP:{address}",
                ]
            )
        )  # fmt: skip
    (tls / "truststore.pem").write_text(utility_ca_pem or PLACEHOLDER_TRUSTSTORE_PEM)
    run(Command(args=["curl", "-fsSL", CONFIG_URL, "-o", str(ems_dir / CONFIG_FILE)]))
    run(compose_command(ems_dir, "up", "-d", "--force-recreate", DER_INGRESS_SERVICE))
    wait_for_log(run, ems_dir, DER_INGRESS_SERVICE, READY_LINE)
    out = run(
        compose_command(ems_dir, "ps", "-q", "--status", "running", DER_INGRESS_SERVICE)
    )
    running = bool(out.stdout.strip())
    return VerifyCheck(
        name="DER ingress listening on 8443",
        ok=running,
        detail="the utility posts DER events here" if running else "not running",
        hint=f"sudo docker compose -f /opt/arcnode/docker-compose.yaml logs {DER_INGRESS_SERVICE}",
    )
