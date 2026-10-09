"""Unit tests for the on-prem PostgreSQL page — reachable on Docker's
network (the range Docker picked), the cloud's four databases, their
connection URLs saved for the EMS containers."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.wizard.postgres_service import PostgresStepNotAvailableError
from src.wizard.wizard_fixtures import FakeRunner, make_postgres_service, ok, tracker
from src.wizard.wizard_record import CommandOutput, Deployment, PasswordRequest

PASSWORD = "Pg-pass'1 ok"  # a quote and a space: must survive psql + the URLs
SAVED = "DOCUMENT_URL, VECTOR_URL, TIMESERIES_URL, DER_CONTROL_URL"


def test_apply_sets_up_postgres_and_every_check_passes(tmp_path: Path) -> None:
    # Arrange
    service = make_postgres_service(tmp_path)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    actual_rows = [(check.name, check.ok, check.detail) for check in result.checks]
    assert actual_rows == [
        ("PostgreSQL 17 running", True, "active"),
        ("Accepts the password you set", True, "connected as postgres"),
        (
            "EMS databases",
            True,
            "ems_document, ems_vector, ems_timeseries, ems_dercontrol",
        ),
        ("TimescaleDB extension", True, "2.30.2 in ems_timeseries"),
        ("pgvector extension", True, "0.8.0 in ems_vector"),
        ("Listens on localhost + Docker's gateway", True, "localhost,172.23.0.1"),
        (
            "Accepts only loopback + Docker's range",
            True,
            "host rules 127.0.0.1/32, ::1/128, 172.23.0.0/16",
        ),
        (
            "A container on the arcnode network connects",
            True,
            "postgres:17-alpine at 172.23.0.2 → 172.23.0.1:5432/ems_document",
        ),
        (
            "Saved for the EMS services",
            True,
            f"{tmp_path / 'secrets.env'} (root only): {SAVED}",
        ),
    ]
    assert result.verified
    assert tracker(tmp_path).is_done("postgres")


def test_postgres_trusts_the_range_docker_picked(tmp_path: Path) -> None:
    # Arrange
    runner = FakeRunner()
    service = make_postgres_service(tmp_path, runner=runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: read from `docker network inspect`, written to its own files
    writes = {c.args[1]: c.input for c in runner.calls if c.args[0] == "tee"}
    assert writes == {
        "/etc/postgresql/17/main/conf.d/arcnode.conf": (
            "listen_addresses = 'localhost,172.23.0.1'\n"
        ),
        "/etc/postgresql/17/main/pg_hba.d/arcnode.conf": (
            "host all all 172.23.0.0/16 scram-sha-256\n"
        ),
    }


def test_no_docker_network_stops_before_touching_postgres(tmp_path: Path) -> None:
    # Arrange: the Docker page never ran (or its network was removed)
    runner = FakeRunner()
    runner.queries["network inspect"] = CommandOutput(
        returncode=1, stdout="Error response from daemon: network arcnode not found\n"
    )
    service = make_postgres_service(tmp_path, runner=runner)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    assert [(c.name, c.ok) for c in result.checks] == [
        ("Docker's arcnode network", False)
    ]
    assert (
        result.checks[0].hint == "Finish the Docker page first; sudo docker network ls"
    )
    assert not [c for c in runner.calls if c.args[0] in ("tee", "runuser")]


def test_password_never_reaches_any_command_line(tmp_path: Path) -> None:
    # Arrange: argv is visible to every user via ps
    runner = FakeRunner()
    service = make_postgres_service(tmp_path, runner=runner)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: it went in through stdin/env only
    assert all(PASSWORD not in " ".join(call.args) for call in runner.calls)
    assert any(PASSWORD in call.env.values() for call in runner.calls)


def test_saves_the_clouds_four_urls_and_nothing_else(tmp_path: Path) -> None:
    # Arrange: an existing secrets.env from a later service must survive
    (tmp_path / "secrets.env").write_text("OTHER_SECRET=keep\n")
    service = make_postgres_service(tmp_path)

    # Act
    service.apply(PasswordRequest(password=PASSWORD))

    # Assert: same names + URL shape as the cloud; password percent-encoded
    secrets = tmp_path / "secrets.env"
    encoded = "Pg-pass%271%20ok"
    host = f"postgres://postgres:{encoded}@172.23.0.1:5432"
    assert secrets.read_text() == (
        "OTHER_SECRET=keep\n"
        f"DOCUMENT_URL={host}/ems_document\n"
        f"VECTOR_URL={host}/ems_vector\n"
        f"TIMESERIES_URL={host}/ems_timeseries\n"
        f"DER_CONTROL_URL={host}/ems_dercontrol\n"
    )
    assert secrets.stat().st_mode & 0o777 == 0o600


def test_open_to_the_whole_network_fails_the_access_check(tmp_path: Path) -> None:
    # Arrange: the playbook's pg_hba line — 0.0.0.0/0
    runner = FakeRunner()
    runner.queries["pg_hba_file_rules"] = ok(
        "127.0.0.1|255.255.255.255\n0.0.0.0|0.0.0.0\n"
    )
    service = make_postgres_service(tmp_path, runner=runner)

    # Act
    result = service.apply(PasswordRequest(password=PASSWORD))

    # Assert
    access = result.checks[6]
    assert (access.ok, access.detail) == (
        False,
        "host rules 127.0.0.1/32, 0.0.0.0/0 — 0.0.0.0/0 is outside Docker's "
        "172.23.0.0/16",
    )
    assert not result.verified
    assert not tracker(tmp_path).is_done("postgres")


def test_a_container_that_cant_connect_says_why(tmp_path: Path) -> None:
    # Arrange: Postgres came up before Docker's bridge existed (boot order)
    runner = FakeRunner()
    runner.queries["inet_client_addr"] = CommandOutput(
        returncode=2,
        # psql's real two-line error: the cause is on the first line
        stdout='psql: error: connection to server at "172.23.0.1", port 5432 '
        "failed: Connection refused\n"
        "\tIs the server running on that host and accepting TCP/IP connections?\n",
    )
    service = make_postgres_service(tmp_path, runner=runner)

    # Act
    container = service.apply(PasswordRequest(password=PASSWORD)).checks[7]

    # Assert
    assert container.ok is False
    assert container.detail.endswith("Connection refused")
    assert container.hint == (
        "sudo ss -ltnp | grep 5432; "
        "sudo tail -n 50 /var/log/postgresql/postgresql-17-main.log"
    )


def test_cloud_has_no_postgres_step(tmp_path: Path) -> None:
    # Arrange: cloud databases are managed services
    service = make_postgres_service(tmp_path, deployment=Deployment.CLOUD)

    # Act / Assert
    with pytest.raises(PostgresStepNotAvailableError):
        service.apply(PasswordRequest(password=PASSWORD))


def test_weak_password_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PasswordRequest(password="password")
