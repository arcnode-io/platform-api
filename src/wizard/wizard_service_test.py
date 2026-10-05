"""Unit tests for WizardService's real apply logic."""

from pathlib import Path

import pytest

from src.wizard.wizard_record import ApiKeyInput, ApplyRequest, HumanAuthInput, TlsInput
from src.wizard.wizard_service import WizardAlreadyAppliedError, WizardService

OPERATOR_PASSWORD = "Correct-Horse1!"
VIEWER_PASSWORD = "Another-Strong1!"


def _service(tmp_path: Path) -> WizardService:
    return WizardService(
        secrets_env_path=tmp_path / "secrets.env",
        tls_cert_path=tmp_path / "tls" / "cert.pem",
        tls_key_path=tmp_path / "tls" / "key.pem",
        applied_marker_path=tmp_path / "applied",
    )


def _request(
    *,
    api_keys: dict[str, ApiKeyInput] | None = None,
    tls: TlsInput | None = None,
) -> ApplyRequest:
    return ApplyRequest(
        api_keys=api_keys or {},
        tls=tls or TlsInput(mode="selfsigned"),
        human_auth=HumanAuthInput(
            operator_password=OPERATOR_PASSWORD,
            operator_confirm=OPERATOR_PASSWORD,
            viewer_password=VIEWER_PASSWORD,
            viewer_confirm=VIEWER_PASSWORD,
        ),
    )


def test_apply_writes_api_keys_to_secrets_env(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request(
        api_keys={"openweathermap": ApiKeyInput(key="owm-key-123", skipped=False)}
    )

    # Act
    service.apply(request)

    # Assert
    actual = (tmp_path / "secrets.env").read_text()
    assert "OPENWEATHERMAP_API_KEY=owm-key-123" in actual


def test_apply_skips_skipped_api_keys(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request(
        api_keys={"gridstatus": ApiKeyInput(key="should-not-appear", skipped=True)}
    )

    # Act
    service.apply(request)

    # Assert
    actual = (tmp_path / "secrets.env").read_text()
    assert "GRIDSTATUS_API_KEY" not in actual


def test_apply_omits_empty_unskipped_key(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request(api_keys={"openweathermap": ApiKeyInput(key="", skipped=False)})

    # Act
    service.apply(request)

    # Assert
    actual = (tmp_path / "secrets.env").read_text()
    assert "OPENWEATHERMAP_API_KEY" not in actual


def test_apply_writes_operator_and_viewer_passwords(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request()

    # Act
    service.apply(request)

    # Assert
    actual = (tmp_path / "secrets.env").read_text()
    assert f"AUTH_OPERATOR_PW={OPERATOR_PASSWORD}" in actual
    assert f"AUTH_VIEWER_PW={VIEWER_PASSWORD}" in actual


def test_apply_secrets_env_is_not_world_readable(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request()

    # Act
    service.apply(request)

    # Assert
    mode = (tmp_path / "secrets.env").stat().st_mode & 0o777
    assert mode == 0o600


def test_apply_generates_selfsigned_cert_via_openssl(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request(tls=TlsInput(mode="selfsigned"))

    # Act
    service.apply(request)

    # Assert
    cert = (tmp_path / "tls" / "cert.pem").read_text()
    key = (tmp_path / "tls" / "key.pem").read_text()
    assert "BEGIN CERTIFICATE" in cert
    assert "PRIVATE KEY" in key


def test_apply_writes_uploaded_cert_as_is(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    request = _request(
        tls=TlsInput(
            mode="upload",
            cert_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
            key_pem="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
        )
    )

    # Act
    service.apply(request)

    # Assert
    actual_cert = (tmp_path / "tls" / "cert.pem").read_text()
    assert actual_cert == (
        "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
    )


def test_apply_marks_applied(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)

    # Act
    assert service.is_applied() is False
    service.apply(_request())

    # Assert
    assert service.is_applied() is True


def test_apply_second_call_raises(tmp_path: Path) -> None:
    # Arrange
    service = _service(tmp_path)
    service.apply(_request())

    # Act + Assert
    with pytest.raises(WizardAlreadyAppliedError):
        service.apply(_request())


def test_tls_upload_mode_requires_both_pem_fields() -> None:
    # Arrange + Act + Assert
    with pytest.raises(ValueError, match="cert_pem and key_pem"):
        TlsInput(mode="upload", cert_pem="only-cert")


def test_human_auth_rejects_operator_password_mismatch() -> None:
    # Arrange + Act + Assert
    with pytest.raises(ValueError, match="operator password"):
        HumanAuthInput(
            operator_password=OPERATOR_PASSWORD,
            operator_confirm="different",
            viewer_password=VIEWER_PASSWORD,
            viewer_confirm=VIEWER_PASSWORD,
        )


def test_human_auth_rejects_password_missing_uppercase() -> None:
    # Arrange + Act + Assert
    with pytest.raises(ValueError, match="uppercase"):
        HumanAuthInput(
            operator_password="lowercase1!",
            operator_confirm="lowercase1!",
            viewer_password=VIEWER_PASSWORD,
            viewer_confirm=VIEWER_PASSWORD,
        )


def test_human_auth_rejects_password_missing_number() -> None:
    # Arrange + Act + Assert
    with pytest.raises(ValueError, match="number"):
        HumanAuthInput(
            operator_password="NoDigitsHere!",
            operator_confirm="NoDigitsHere!",
            viewer_password=VIEWER_PASSWORD,
            viewer_confirm=VIEWER_PASSWORD,
        )


def test_human_auth_rejects_password_missing_special_char() -> None:
    # Arrange + Act + Assert
    with pytest.raises(ValueError, match="special character"):
        HumanAuthInput(
            operator_password="NoSpecial1",
            operator_confirm="NoSpecial1",
            viewer_password=VIEWER_PASSWORD,
            viewer_confirm=VIEWER_PASSWORD,
        )
