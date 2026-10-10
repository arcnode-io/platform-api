"""Unit tests for the cloud wizard's setup token — the wizard refuses every
change until the stack owner's token is sent, and the page itself still loads."""

from pathlib import Path

from src.wizard.controller_fixtures import wizard_client
from src.wizard.setup_token import TOKEN_HEADER, read_or_create_token
from src.wizard.wizard_record import Deployment

TOKEN = "stack-owner-token"


def test_token_is_created_once_and_kept(tmp_path: Path) -> None:
    # Arrange
    token_file = tmp_path / "setup-token"

    # Act
    first = read_or_create_token(token_file)
    second = read_or_create_token(token_file)

    # Assert — the same token every time, readable only by root
    assert first == second
    assert len(first) >= 32
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_cloud_change_without_token_is_refused(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD, setup_token=TOKEN)

    # Act
    response = client.post("/api/preflight")

    # Assert
    assert response.status_code == 401


def test_cloud_change_with_token_goes_through(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD, setup_token=TOKEN)

    # Act
    response = client.post("/api/preflight", headers={TOKEN_HEADER: TOKEN})

    # Assert
    assert response.status_code == 200


def test_page_loads_without_token(tmp_path: Path) -> None:
    # Arrange
    client = wizard_client(tmp_path, deployment=Deployment.CLOUD, setup_token=TOKEN)

    # Act
    response = client.get("/api/config")

    # Assert — the browser has to read the page before it can send the token
    assert response.status_code == 200
