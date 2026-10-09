"""Unit tests for the Neo4j page's failing rows — each says what was seen
and how to debug it."""

from pathlib import Path

from src.wizard.wizard_fixtures import FakeRunner, make_neo4j_service, ok
from src.wizard.wizard_record import CommandOutput, PasswordRequest

PASSWORD = "Ne-4j'pass 1!"


def test_listening_beyond_the_gateway_fails(tmp_path: Path) -> None:
    # Arrange: the browser port is back on, on every address
    runner = FakeRunner()
    runner.outputs["ss"] = ok(
        "LISTEN 0 4096 [::ffff:172.23.0.1]:7687 *:*\nLISTEN 0 4096 *:7474 *:*\n"
    )
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    listens = service.apply(PasswordRequest(password=PASSWORD)).checks[3]

    # Assert
    assert (listens.ok, listens.detail) == (
        False,
        "172.23.0.1:7687, *:7474 (want 172.23.0.1:7687 only)",
    )


def test_a_container_that_cant_connect_says_why(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["neo4j:2026.09.0-community"] = CommandOutput(
        returncode=1,
        stdout="Unable to connect to 172.23.0.1:7687, ensure the database is "
        "running and that there is a working network connection to it.\n",
    )
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    container = service.apply(PasswordRequest(password=PASSWORD)).checks[4]

    # Assert
    assert container.ok is False
    assert container.detail.startswith("Unable to connect to 172.23.0.1:7687")
