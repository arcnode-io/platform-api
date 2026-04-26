"""Session-scoped testcontainers for the platform-api integration tests.

Spins three containers once per session and stitches them into a Config that
points the AppModule at all of them — same code paths as production, just
different URLs.
"""

from collections.abc import Generator
from ipaddress import IPv4Address

import pytest

from src.config import Config, LogLevel, PostgresHost
from tests.fixtures.containers import (
    Container,
    start_edp_api,
    start_localstack,
    start_postgres,
)

POSTGRES_PASSWORD: str = "test"  # noqa: S105 — testcontainer credential


@pytest.fixture(scope="session")
def postgres() -> Generator[Container]:
    """Real Postgres in a Docker container."""
    with start_postgres(password=POSTGRES_PASSWORD) as c:
        yield c


@pytest.fixture(scope="session")
def localstack() -> Generator[Container]:
    """LocalStack with S3 + SES enabled."""
    with start_localstack() as c:
        yield c


@pytest.fixture(scope="session")
def edp_api() -> Generator[Container]:
    """Real `edp-api:test` Docker image (built by edp-api repo)."""
    with start_edp_api() as c:
        yield c


@pytest.fixture(scope="session")
def integration_config(
    postgres: Container,
    localstack: Container,
    edp_api: Container,
    monkeypatch_session: pytest.MonkeyPatch,
) -> Config:
    """Stitch container URLs into a Config that AppModule consumes."""
    monkeypatch_session.setenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)
    return Config(
        log_level=LogLevel.DEBUG,
        port=8000,
        host=IPv4Address("127.0.0.1"),
        e2e=True,
        reload=False,
        postgres_host=PostgresHost.LOCALHOST,
        postgres_port=postgres.port,
        edp_api_url=edp_api.url,
        s3_endpoint_url=localstack.url,
        s3_bucket="platform-api-artifacts-test",
        ses_endpoint_url=localstack.url,
        ses_sender_email="noreply@arcnode.test",
    )


@pytest.fixture(scope="session")
def monkeypatch_session() -> Generator[pytest.MonkeyPatch]:
    """Session-scoped MonkeyPatch (pytest only ships function-scoped by default)."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()
