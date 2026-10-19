"""Unit tests for the on-prem HTTPS certificate page. openssl is real (the key,
the signing request and every certificate check); docker and compose are fake."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.wizard.https_service import HttpsService
from src.wizard.system_runner import run_system_command
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import (
    Command,
    CommandOutput,
    HttpsCertificate,
    SigningRequest,
)

HOST = "ems.plant.local"


class OpensslRunner(FakeRunner):
    """Real openssl for the certificate work; the rest stays canned."""

    def __call__(self, command: Command) -> CommandOutput:
        if command.args[0] == "openssl" and "s_client" not in command.args:
            self.calls.append(command)
            return run_system_command(command)
        return super().__call__(command)


def _openssl(*args: str) -> None:
    out = run_system_command(Command(args=["openssl", *args]))
    assert out.returncode == 0, out.stdout


def _sign(csr_pem: str, tmp_path: Path, host: str = HOST) -> str:
    """The customer's IT: a test CA signs the request; returns leaf + CA chain."""
    ca = tmp_path / "it-ca"
    ca.mkdir(exist_ok=True)
    key, root, csr, ext, leaf = (
        str(ca / name)
        for name in ("ca-key.pem", "ca.pem", "req.csr", "ext.cnf", "leaf.pem")
    )
    _openssl(
        "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-nodes", "-keyout", key, "-out", root, "-days", "30", "-subj", "/CN=Plant IT Root",
    )  # fmt: skip
    (ca / "req.csr").write_text(csr_pem)
    (ca / "ext.cnf").write_text(f"subjectAltName=DNS:{host}\n")
    _openssl(
        "x509", "-req", "-in", csr, "-CA", root, "-CAkey", key, "-CAcreateserial",
        "-out", leaf, "-days", "30", "-extfile", ext,
    )  # fmt: skip
    return (ca / "leaf.pem").read_text() + (ca / "ca.pem").read_text()


def _service(tmp_path: Path, runner: FakeRunner) -> HttpsService:
    return HttpsService(tracker=tracker(tmp_path), ems_dir=tmp_path / "opt", run=runner)


def test_the_signing_request_names_the_box_and_keeps_the_key_on_it(
    tmp_path: Path,
) -> None:
    # Arrange
    service = _service(tmp_path, OpensslRunner())

    # Act
    actual = service.request_signing(SigningRequest(hostname=HOST))

    # Assert
    assert actual.csr_pem.startswith("-----BEGIN CERTIFICATE REQUEST-----")
    assert "PRIVATE KEY" not in actual.csr_pem
    text = run_system_command(
        Command(args=["openssl", "req", "-noout", "-text"], input=actual.csr_pem)
    ).stdout
    assert f"DNS:{HOST}" in text
    key = tmp_path / "opt" / "tls" / "pending-key.pem"
    assert key.stat().st_mode & 0o777 == 0o600


def test_a_signed_certificate_is_installed_and_served(tmp_path: Path) -> None:
    # Arrange
    runner = OpensslRunner()
    service = _service(tmp_path, runner)
    chain = _sign(
        service.request_signing(SigningRequest(hostname=HOST)).csr_pem, tmp_path
    )
    leaf = chain.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    runner.queries["s_client"] = ok(f"CONNECTED(00000003)\n{leaf}")

    # Act
    result = service.apply(HttpsCertificate(certificate_pem=chain))

    # Assert
    assert [(check.name, check.ok) for check in result.checks] == [
        ("Certificate matches the key made on this box", True),
        (f"Issued for {HOST}", True),
        ("HTTPS front end running", True),
        (f"https://{HOST} serves this certificate", True),
    ]
    assert result.verified
    tls = tmp_path / "opt" / "tls"
    assert (tls / "server.pem").read_text() == chain
    assert (tls / "server-key.pem").stat().st_mode & 0o777 == 0o600
    # The utility-facing DER ingress serves the same certificate.
    assert (tmp_path / "opt" / "der-control-tls" / "cert.pem").read_text() == chain
    assert tracker(tmp_path).is_done("https")


def test_a_certificate_for_another_key_installs_nothing(tmp_path: Path) -> None:
    # Arrange: IT signed a request made somewhere else
    service = _service(tmp_path, OpensslRunner())
    service.request_signing(SigningRequest(hostname=HOST))
    other = _service(tmp_path / "other", OpensslRunner())
    chain = _sign(
        other.request_signing(SigningRequest(hostname=HOST)).csr_pem, tmp_path
    )

    # Act
    result = service.apply(HttpsCertificate(certificate_pem=chain))

    # Assert
    assert result.checks[0].name == "Certificate matches the key made on this box"
    assert not result.checks[0].ok
    assert not result.verified
    assert not (tmp_path / "opt" / "tls" / "server.pem").exists()


def test_a_certificate_for_another_name_installs_nothing(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, OpensslRunner())
    csr = service.request_signing(SigningRequest(hostname=HOST)).csr_pem
    chain = _sign(csr, tmp_path, host="historian.plant.local")

    # Act
    result = service.apply(HttpsCertificate(certificate_pem=chain))

    # Assert
    assert (result.checks[1].name, result.checks[1].ok) == (f"Issued for {HOST}", False)
    assert not result.verified
    assert not (tmp_path / "opt" / "tls" / "server.pem").exists()


def test_skipping_keeps_plain_http(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path, OpensslRunner())

    # Act
    result = service.skip()

    # Assert
    assert result.verified
    assert tracker(tmp_path).is_done("https")


@pytest.mark.parametrize("hostname", ["", "10.0.4.20", "ems plant", "-ems.local"])
def test_the_name_must_be_a_dns_name(hostname: str) -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        SigningRequest(hostname=hostname)
