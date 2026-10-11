"""Unit tests for the cloud password page — the three customer passwords are
saved to secrets.env, and the page is done only once they're on disk."""

from pathlib import Path

import pytest

from src.wizard.cloud_secrets_service import CloudSecretsService, CloudSecretsStepNotAvailableError
from src.wizard.wizard_fixtures import tracker
from src.wizard.wizard_record import CloudSecrets, Deployment

SECRETS = CloudSecrets(
    operator_password="Operator-pw-1!",
    viewer_password="Viewer-pw-1!",
    grafana_password="Grafana-pw-1!",
)


def test_passwords_are_saved_and_the_page_is_done(tmp_path: Path) -> None:
    # Arrange
    service = CloudSecretsService(
        deployment=Deployment.CLOUD,
        tracker=tracker(tmp_path),
        secrets_env_path=tmp_path / "secrets.env",
    )

    # Act
    result = service.apply(SECRETS)

    # Assert
    assert result.verified
    assert [c.name for c in result.checks] == ["Saved for the EMS services"]
    saved = (tmp_path / "secrets.env").read_text()
    assert "AUTH_OPERATOR_PW=Operator-pw-1!" in saved
    assert "AUTH_VIEWER_PW=Viewer-pw-1!" in saved
    assert "GF_SECURITY_ADMIN_PASSWORD=Grafana-pw-1!" in saved
    assert tracker(tmp_path).is_done("cloud_secrets")


def test_on_prem_has_no_cloud_password_page(tmp_path: Path) -> None:
    # Arrange — on-prem collects these on its own pages
    service = CloudSecretsService(
        deployment=Deployment.ON_PREM,
        tracker=tracker(tmp_path),
        secrets_env_path=tmp_path / "secrets.env",
    )

    # Act / Assert
    with pytest.raises(CloudSecretsStepNotAvailableError):
        service.apply(SECRETS)
