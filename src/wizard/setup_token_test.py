"""Unit tests for the cloud wizard's setup token — the wizard refuses every
change until the stack owner's token is sent, and the page itself still loads."""

from pathlib import Path

import pytest

from src.wizard.controller_fixtures import wizard_client
from src.wizard.setup_token import (
    TOKEN_HEADER,
    read_or_create_token,
    setup_token_from_env_file,
    token_for,
)
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


def test_token_is_read_from_secrets_env(tmp_path: Path) -> None:
    # Arrange — the file UserData writes, with other secrets around it
    env_file = tmp_path / "secrets.env"
    env_file.write_text(
        "AUTH_JWT_SECRET=abc\nSETUP_TOKEN=stack-owner-token\nGRAFANA=x\n"
    )

    # Act
    token = setup_token_from_env_file(env_file)

    # Assert
    assert token == "stack-owner-token"


def test_missing_token_line_is_none(tmp_path: Path) -> None:
    # Arrange
    env_file = tmp_path / "secrets.env"
    env_file.write_text("AUTH_JWT_SECRET=abc\n")

    # Act
    token = setup_token_from_env_file(env_file)

    # Assert
    assert token is None


def test_cloud_wizard_takes_its_token_from_secrets_env(tmp_path: Path) -> None:
    # Arrange
    env_file = tmp_path / "secrets.env"
    env_file.write_text("SETUP_TOKEN=stack-owner-token\n")

    # Act
    token = token_for(Deployment.CLOUD, env_file)

    # Assert
    assert token == "stack-owner-token"


def test_on_prem_wizard_has_no_token_gate(tmp_path: Path) -> None:
    # Arrange — on-prem is reached on the LAN and never had a stack output to read
    env_file = tmp_path / "secrets.env"
    env_file.write_text("")

    # Act
    token = token_for(Deployment.ON_PREM, env_file)

    # Assert
    assert token is None


def test_cloud_wizard_without_a_token_refuses_to_start(tmp_path: Path) -> None:
    # Arrange — UserData didn't write SETUP_TOKEN, so nothing could unlock the wizard
    env_file = tmp_path / "secrets.env"
    env_file.write_text("AUTH_JWT_SECRET=abc\n")

    # Act / Assert — fail fast rather than run an open wizard
    with pytest.raises(RuntimeError):
        token_for(Deployment.CLOUD, env_file)
