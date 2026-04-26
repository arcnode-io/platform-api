"""Testcontainer fixtures with dynamic port allocation."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.localstack import LocalStackContainer
from testcontainers.postgres import PostgresContainer


@dataclass(frozen=True)
class Container:
    """Connection info for a running testcontainer.

    Attributes:
        host: Container host (always localhost)
        port: Dynamic mapped port
        url: Pre-built connection URL
    """

    host: str
    port: int
    url: str


@contextmanager
def _start_container(
    image: str,
    port: int,
    wait_for_log: str,
) -> Generator[Container]:
    """Start a generic Docker container with dynamic port. Internal building block.

    Args:
        image: Docker image (e.g. "postgres:15")
        port: Internal container port to expose
        wait_for_log: Log message indicating readiness

    Yields:
        Container with http:// URL and dynamic port
    """
    c = (
        DockerContainer(image)
        .with_exposed_ports(port)
        .waiting_for(LogMessageWaitStrategy(wait_for_log))
    )

    with c:
        mapped = int(c.get_exposed_port(port))
        yield Container(
            host="localhost",
            port=mapped,
            url=f"http://localhost:{mapped}",
        )


@contextmanager
def start_postgres(
    password: str,
    image: str = "postgres:15",
    username: str = "postgres",
    dbname: str = "postgres",
) -> Generator[Container]:
    """Start a Postgres container with dynamic port.

    Args:
        password: DB password
        image: Docker image (postgres:15, timescale/timescaledb:latest-pg15, pgvector/pgvector:pg16)
        username: Database username
        dbname: Database name

    Yields:
        Container with postgresql:// URL and dynamic port
    """
    with PostgresContainer(
        image, username=username, password=password, dbname=dbname
    ) as c:
        port = int(c.get_exposed_port(5432))
        yield Container(
            host="localhost",
            port=port,
            url=f"postgres://{username}:{password}@localhost:{port}/{dbname}",
        )


@contextmanager
def start_localstack(
    image: str = "localstack/localstack:3.7",
) -> Generator[Container]:
    """Start LocalStack with ONLY S3 + SES. Yields the dynamic edge URL.

    `with_services` sets `SERVICES=s3,ses` (the documented LocalStack env var) so
    we don't init Lambda/SNS/etc. Combined with the default `EAGER_SERVICE_LOADING=0`,
    even s3 + ses only spin up on first use — fastest possible startup.

    Pinned to `:3.7` — the last image tag where SES is freely available without a
    Pro license. `:latest` started gating SES behind LocalStack Pro mid-2024.
    """
    container = LocalStackContainer(image=image).with_services("s3", "ses")
    with container as ls:
        url = ls.get_url()
        port = int(url.rsplit(":", 1)[-1])
        yield Container(host="localhost", port=port, url=url)


@contextmanager
def start_edp_api(
    image: str = "edp-api:test",
    port: int = 8000,
) -> Generator[Container]:
    """Run the published `edp-api:test` Docker image. Caller supplies the built tag.

    The image is built by edp-api's own `tests/test_edp_api_container.py`. CI shares
    the build cache between repos; locally, run `docker build -t edp-api:test ../edp-api`
    once before integration tests.
    """
    container = (
        DockerContainer(image)
        .with_exposed_ports(port)
        .with_env("ENV", "beta")
        .waiting_for(LogMessageWaitStrategy("Application startup complete"))
    )
    with container as c:
        mapped = int(c.get_exposed_port(port))
        yield Container(
            host="localhost",
            port=mapped,
            url=f"http://localhost:{mapped}",
        )
