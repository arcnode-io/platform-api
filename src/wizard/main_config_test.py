"""The wizard's server settings. Browsers hold idle connections between steps,
so uvicorn must keep them open longer than a person takes to read a page."""

from pathlib import Path

import pytest

from src.wizard.main import KEEP_ALIVE_SECONDS, TlsFiles, tls_files
from src.wizard.wizard_record import Deployment


def test_keep_alive_outlasts_a_person_reading_a_step() -> None:
    # Arrange — uvicorn's own default is 5 seconds, which drops a browser's idle connection

    # Act
    keep_alive = KEEP_ALIVE_SECONDS

    # Assert
    assert keep_alive >= 60


def test_the_cloud_wizard_serves_https_from_the_boxs_certificate(
    tmp_path: Path,
) -> None:
    """A cloud customer's passwords cross the internet to the wizard, so it speaks TLS there."""
    # Arrange
    (tmp_path / "server.pem").write_text("cert")
    (tmp_path / "server-key.pem").write_text("key")

    # Act
    tls = tls_files(Deployment.CLOUD, tmp_path)

    # Assert
    assert tls == TlsFiles(
        certfile=tmp_path / "server.pem", keyfile=tmp_path / "server-key.pem"
    )


def test_the_on_prem_wizard_stays_plain_http_on_the_lan(tmp_path: Path) -> None:
    # Arrange — even with a certificate on disk (the HMI page writes one later)
    (tmp_path / "server.pem").write_text("cert")
    (tmp_path / "server-key.pem").write_text("key")

    # Act + Assert
    assert tls_files(Deployment.ON_PREM, tmp_path) is None


def test_a_cloud_wizard_without_a_certificate_refuses_to_start_in_the_clear(
    tmp_path: Path,
) -> None:
    """UserData writes the self-signed certificate before it starts the wizard; if it is missing
    something is wrong, and serving customer passwords over HTTP is the worse outcome.
    """
    # Arrange + Act + Assert
    with pytest.raises(FileNotFoundError):
        tls_files(Deployment.CLOUD, tmp_path)
