"""Unit tests for the on-prem DER control API page — its overlay carries the
order's site and the box's address, the service starts, and its health answers."""

import hashlib
from pathlib import Path

import pytest
import yaml

from src.wizard.der_control_service import DerControlService, lfdi_from_cert_pem
from src.wizard.ems_cfg import DER_CONTROL_CFG_FILE
from src.wizard.site_fixtures import TEST_ORDER
from src.wizard.wizard_fixtures import FakeRunner, ok, tracker
from src.wizard.wizard_record import DerControlRequest


def make_der_control(tmp_path: Path) -> DerControlService:
    return DerControlService(
        tracker=tracker(tmp_path),
        order_dir=TEST_ORDER,
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=FakeRunner(),
    )


def test_der_control_writes_its_overlay_and_verifies(tmp_path: Path) -> None:
    # Arrange
    service = make_der_control(tmp_path)

    # Act
    result = service.apply(DerControlRequest(utility_mirror_url=None))

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("DER control API running", True),
        ("DER control API healthy", True),
        ("Saved for the DER control API", True),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("der_control_api")
    written = yaml.safe_load((tmp_path / "opt" / DER_CONTROL_CFG_FILE).read_text())
    assert written == {
        "siteId": "test_site",
        "publicBaseUrl": "https://10.0.0.209:8443",
    }


def test_utility_url_is_written_when_the_customer_gives_one(tmp_path: Path) -> None:
    # Arrange
    service = make_der_control(tmp_path)

    # Act
    service.apply(DerControlRequest(utility_mirror_url="https://derms.utility.example"))

    # Assert
    written = yaml.safe_load((tmp_path / "opt" / DER_CONTROL_CFG_FILE).read_text())
    assert written["utilityMirrorUrl"] == "https://derms.utility.example"


def test_skipping_the_der_page_lets_the_wizard_continue(tmp_path: Path) -> None:
    # Arrange — the utility isn't connected yet; the customer moves on
    service = make_der_control(tmp_path)

    # Act
    result = service.skip()

    # Assert
    assert result.verified
    assert [c.name for c in result.checks] == ["Skipped for now"]
    assert tracker(tmp_path).is_done("der_control_api")


LFDI_A = "a" * 40
LFDI_B = "0123456789abcdef" * 2 + "01234567"


def test_allowed_lfdis_are_written_to_secrets_env(tmp_path: Path) -> None:
    # Arrange — the DERMS certificate's device identities, comma and newline separated
    service = make_der_control(tmp_path)

    # Act
    service.apply(DerControlRequest(lfdi_allowlist=f"{LFDI_A},\n{LFDI_B}"))

    # Assert — one line in secrets.env, spaces between the ids
    saved = (tmp_path / "secrets.env").read_text()
    assert f"DER_CONTROL_LFDI_ALLOWLIST={LFDI_A} {LFDI_B}\n" in saved


def test_an_lfdi_that_is_not_40_hex_is_refused() -> None:
    # Arrange + Act / Assert — a typo here would silently refuse the real utility
    with pytest.raises(ValueError):
        DerControlRequest(lfdi_allowlist="not-an-lfdi")


def test_an_empty_allowlist_is_allowed_and_fails_closed(tmp_path: Path) -> None:
    # Arrange + Act
    make_der_control(tmp_path).apply(DerControlRequest(lfdi_allowlist=""))

    # Assert — written empty; der-control-api refuses everyone until one is given
    assert "DER_CONTROL_LFDI_ALLOWLIST=\n" in (tmp_path / "secrets.env").read_text()


CERT_PEM = "-----BEGIN CERTIFICATE-----\nMIIBcert\n-----END CERTIFICATE-----\n"
KEY_PEM = "-----BEGIN PRIVATE KEY-----\nMIIBkey\n-----END PRIVATE KEY-----\n"
CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIBca\n-----END CERTIFICATE-----\n"


def test_utility_identity_files_are_written_with_the_key_private(
    tmp_path: Path,
) -> None:
    # Arrange
    service = make_der_control(tmp_path)

    # Act
    service.apply(
        DerControlRequest(
            device_cert_pem=CERT_PEM, device_key_pem=KEY_PEM, utility_ca_pem=CA_PEM
        )
    )

    # Assert — the mount sources der-control-api reads, key readable by owner only
    ems = tmp_path / "opt"
    assert (ems / "der-control-client.pem").read_text() == CERT_PEM
    assert (ems / "der-control-utility-ca.pem").read_text() == CA_PEM
    assert (ems / "der-control-client-key.pem").read_text() == KEY_PEM
    assert (ems / "der-control-client-key.pem").stat().st_mode & 0o777 == 0o600


def test_a_certificate_without_its_key_is_refused() -> None:
    # Arrange + Act / Assert — der-control-api would fail at boot on a half identity
    with pytest.raises(ValueError):
        DerControlRequest(device_cert_pem=CERT_PEM)


def test_no_identity_removes_the_files_so_the_service_boots_without_one(
    tmp_path: Path,
) -> None:
    # Arrange — a previous run left files behind
    ems = tmp_path / "opt"
    ems.mkdir()
    (ems / "der-control-client.pem").write_text(CERT_PEM)

    # Act
    make_der_control(tmp_path).apply(DerControlRequest())

    # Assert
    assert not (ems / "der-control-client.pem").exists()


def test_a_key_that_is_not_pkcs8_is_refused() -> None:
    # Arrange + Act / Assert — der-control-api reads PKCS#8 only; an RSA-only key would fail its boot
    with pytest.raises(ValueError):
        DerControlRequest(
            device_cert_pem=CERT_PEM,
            device_key_pem="-----BEGIN RSA PRIVATE KEY-----\nMIIBkey\n-----END RSA PRIVATE KEY-----\n",
        )


def test_a_cert_that_is_not_pem_is_refused() -> None:
    # Arrange + Act / Assert
    with pytest.raises(ValueError):
        DerControlRequest(device_cert_pem="not a certificate", device_key_pem=KEY_PEM)


def test_lfdi_is_the_first_20_bytes_of_the_certificate_sha256() -> None:
    """The LFDI the utility registers is the client cert's SHA-256, first 40 hex characters."""
    # Arrange — a PEM whose DER body is the bytes b"hello" (base64 of b"hello" is aGVsbG8=)
    pem = "-----BEGIN CERTIFICATE-----\naGVsbG8=\n-----END CERTIFICATE-----\n"

    # Act
    lfdi = lfdi_from_cert_pem(pem)

    # Assert
    assert lfdi == hashlib.sha256(b"hello").hexdigest()[:40]


def test_the_box_confirms_the_lfdi_it_loaded_matches_its_certificate(
    tmp_path: Path,
) -> None:
    # Arrange — der-control-api logs the LFDI it loaded from the mounted certificate
    lfdi = lfdi_from_cert_pem(CERT_PEM)
    runner = FakeRunner()
    runner.queries["logs der-control-api"] = ok(
        f"Started Application in 13 seconds\nutility TLS identity loaded from /app/tls/utility: LFDI {lfdi}\n"
    )
    service = DerControlService(
        tracker=tracker(tmp_path),
        order_dir=TEST_ORDER,
        ems_dir=tmp_path / "opt",
        secrets_env_path=tmp_path / "secrets.env",
        run=runner,
    )

    # Act
    result = service.apply(
        DerControlRequest(device_cert_pem=CERT_PEM, device_key_pem=KEY_PEM)
    )

    # Assert — the check names the LFDI the utility must have registered
    identity = [c for c in result.checks if c.name == "Utility identity loaded"]
    assert identity and identity[0].ok
    assert lfdi in identity[0].detail
