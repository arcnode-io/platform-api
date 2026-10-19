"""Unit tests for the on-prem DER ingress: the 8443 mutual-TLS front door the utility posts to."""

from pathlib import Path

from src.der_control_truststore import PLACEHOLDER_TRUSTSTORE_PEM
from src.wizard.der_control_ingress import start_der_ingress
from src.wizard.wizard_fixtures import FakeRunner

UTILITY_CA = "-----BEGIN CERTIFICATE-----\nMIIutility\n-----END CERTIFICATE-----\n"


def test_the_ingress_trusts_the_utility_and_starts_on_a_self_signed_cert(
    tmp_path: Path,
) -> None:
    # Arrange
    runner = FakeRunner()

    # Act
    check = start_der_ingress(runner, tmp_path, "10.0.4.20", UTILITY_CA)

    # Assert
    assert (check.name, check.ok) == ("DER ingress listening on 8443", True)
    tls = tmp_path / "der-control-tls"
    assert (tls / "truststore.pem").read_text() == UTILITY_CA
    commands = [" ".join(call.args) for call in runner.calls]
    assert any(
        "subjectAltName=IP:10.0.4.20" in c and str(tls / "key.pem") in c
        for c in commands
    )
    assert any("up -d --force-recreate der-control-ingress" in c for c in commands)


def test_a_certificate_already_installed_is_kept(tmp_path: Path) -> None:
    """The HTTPS page's certificate wins; a later DER apply doesn't replace it."""
    # Arrange
    runner = FakeRunner()
    tls = tmp_path / "der-control-tls"
    tls.mkdir()
    (tls / "cert.pem").write_text("from the HTTPS page")
    (tls / "key.pem").write_text("its key")

    # Act
    start_der_ingress(runner, tmp_path, "10.0.4.20", UTILITY_CA)

    # Assert
    assert (tls / "cert.pem").read_text() == "from the HTTPS page"
    assert not any(call.args[:2] == ["openssl", "req"] for call in runner.calls)


def test_no_utility_ca_refuses_every_client(tmp_path: Path) -> None:
    # Act
    start_der_ingress(FakeRunner(), tmp_path, "10.0.4.20", "")

    # Assert
    actual = (tmp_path / "der-control-tls" / "truststore.pem").read_text()
    assert actual == PLACEHOLDER_TRUSTSTORE_PEM
