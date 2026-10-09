"""Unit tests for the on-prem Neo4j page — fixed memory, listens on Docker's
gateway only, the customer's password, GRAPH_URL saved like the cloud's."""

from pathlib import Path

import pytest

from src.wizard.neo4j_service import Neo4jStepNotAvailableError
from src.wizard.wizard_fixtures import FakeRunner, make_neo4j_service, ok, tracker
from src.wizard.wizard_record import CommandOutput, Deployment, PasswordRequest

PASSWORD = "Ne-4j'pass 1!"  # a quote and a space: must survive Cypher + the URL
DENIED = CommandOutput(
    returncode=1,
    stdout="42NFF: syntax error or access rule violation - permission/access "
    "denied. Access denied, see the security logs for details.\n",
)


def test_apply_sets_up_neo4j_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_neo4j_service(tmp_path)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    actual_rows = [(check.name, check.ok, check.detail) for check in result.checks]
    assert actual_rows == [
        ("Neo4j running", True, "active"),
        (
            "Accepts the password you set",
            True,
            "connected as neo4j: 2026.09.0 community",
        ),
        ("Memory fixed", True, "heap 4.00GiB, page cache 4.00GiB"),
        ("Listens on Docker's gateway only", True, "172.23.0.1:7687"),
        (
            "A container on the arcnode network connects",
            True,
            "neo4j:2026.09.0-community → bolt://172.23.0.1:7687",
        ),
        (
            "Saved for the EMS services",
            True,
            f"{tmp_path / 'secrets.env'} (root only): GRAPH_URL",
        ),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("neo4j")


def test_config_pins_memory_and_listens_on_the_gateway(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: neo4j.conf edited in place, then the service (re)started
    edit = next(c.args for c in runner.calls if c.args[0] == "sed")
    assert edit == [
        "sed",
        "-i",
        "-e",
        r"s/^#\?server.default_listen_address=.*/server.default_listen_address=172.23.0.1/",
        "-e",
        r"s/^#\?server.http.enabled=.*/server.http.enabled=false/",
        "-e",
        r"s/^#\?server.memory.heap.initial_size=.*/server.memory.heap.initial_size=4g/",
        "-e",
        r"s/^#\?server.memory.heap.max_size=.*/server.memory.heap.max_size=4g/",
        "-e",
        r"s/^#\?server.memory.pagecache.size=.*/server.memory.pagecache.size=4g/",
        "/etc/neo4j/neo4j.conf",
    ]
    systemctl = [c.args[1:] for c in runner.calls if c.args[0] == "systemctl"]
    assert systemctl[:2] == [["enable", "neo4j"], ["restart", "neo4j"]]


def test_password_is_changed_from_the_default_over_stdin(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: Cypher-escaped params on stdin, the old password in the env
    alter = next(c for c in runner.calls if "ALTER" in (c.input or ""))
    assert alter.input == (
        ":param old => 'neo4j'\n"
        ":param new => 'Ne-4j\\'pass 1!'\n"
        "ALTER CURRENT USER SET PASSWORD FROM $old TO $new;\n"
    )
    assert alter.env == {"NEO4J_PASSWORD": "neo4j"}
    assert all(PASSWORD not in " ".join(call.args) for call in runner.calls)


def test_a_retry_changes_it_from_the_saved_password(tmp_path: Path) -> None:
    # Arrange: an earlier try set + saved a password, then a later row failed
    old = "Old-pass1!"
    (tmp_path / "secrets.env").write_text(
        "GRAPH_URL=bolt://neo4j:Old-pass1%21@172.23.0.1:7687\n"
    )
    runner = FakeRunner()
    runner.queries["FROM $old"] = DENIED  # the default no longer works
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: the default first, then the saved one
    tried = [
        c.env["NEO4J_PASSWORD"] for c in runner.calls if "ALTER" in (c.input or "")
    ]
    assert tried == ["neo4j", old]


def test_saves_graph_url_like_the_cloud(tmp_path: Path) -> None:
    # Arrange: Postgres's URLs are already there and must survive
    (tmp_path / "secrets.env").write_text("DOCUMENT_URL=keep\n")
    service = make_neo4j_service(tmp_path)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: same name as the cloud's Aura URL; password percent-encoded
    assert (tmp_path / "secrets.env").read_text() == (
        "DOCUMENT_URL=keep\n"
        "GRAPH_URL=bolt://neo4j:Ne-4j%27pass%201%21@172.23.0.1:7687\n"
    )


def test_password_not_changed_means_nothing_saved(tmp_path: Path) -> None:
    # Arrange: neither the default nor a saved password works
    runner = FakeRunner()
    runner.queries["FROM $old"] = DENIED
    runner.queries["dbms.components"] = DENIED
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    assert not (tmp_path / "secrets.env").exists()
    password_row = result.checks[1]
    assert (password_row.ok, password_row.detail) == (False, DENIED.stdout.strip())
    assert not result.verified


def test_neo4j_that_dies_on_start_stops_before_the_password(tmp_path: Path) -> None:
    # Arrange: e.g. a heap bigger than the box — the unit exits, bolt never opens
    runner = FakeRunner()
    runner.outputs["ss"] = ok("")
    runner.outputs["systemctl"] = CommandOutput(returncode=3, stdout="failed\n")
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    assert not [c for c in runner.calls if "ALTER" in (c.input or "")]
    running = result.checks[0]
    assert (running.ok, running.detail) == (False, "failed")
    assert running.hint == "sudo systemctl status neo4j; sudo journalctl -u neo4j -n 50"


def test_no_docker_network_stops_before_touching_neo4j(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["network inspect"] = CommandOutput(returncode=1, stdout="")
    service = make_neo4j_service(tmp_path, runner=runner)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Docker's arcnode network", False)
    ]
    assert not [c for c in runner.calls if c.args[0] in ("sed", "systemctl")]


def test_cloud_has_no_neo4j_step(tmp_path: Path) -> None:
    # Arrange: the cloud's graph is Aura (commercial) or Neptune (defense)
    service = make_neo4j_service(tmp_path, deployment=Deployment.CLOUD)

    # Act / Assert
    with pytest.raises(Neo4jStepNotAvailableError):
        service.apply(PasswordRequest(password=PASSWORD))
