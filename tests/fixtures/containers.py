"""Testcontainer fixtures with dynamic port allocation."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import boto3
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.localstack import LocalStackContainer
from testcontainers.postgres import PostgresContainer

# edp-api expects this bucket + key per its cfg.yml `manifest_url`.
EDP_MANIFEST_BUCKET: str = "arcnode-artifacts"
EDP_MANIFEST_KEY: str = "manifest.yaml"


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
    image: str | None = None,
    services: tuple[str, ...] = ("s3", "ses"),
    network: Network | None = None,
    network_alias: str | None = None,
    enable_lambda: bool = False,
) -> Generator[Container]:
    """Start LocalStack with the given services. Yields the dynamic edge URL.

    `with_services` sets `SERVICES=...` (the documented LocalStack env var) so
    only listed services init. Combined with the default `EAGER_SERVICE_LOADING=0`,
    services only spin up on first use — fastest possible startup.

    `network` + `network_alias` let other containers reach LocalStack by hostname
    inside the same Docker network (used by start_edp_api so edp-api's startup
    S3 fetch can resolve `http://<alias>:4566`).

    `enable_lambda=True` mounts the host docker socket so LocalStack can
    spawn lambda runtime containers (required for CFN templates that include
    AWS::Lambda::Function or custom resources backed by Lambda). Off by default
    because most tests don't need it and the mount adds blast radius.

    Image selection:
      - If `image` is None and `LOCALSTACK_AUTH_TOKEN` is set in env, defaults
        to `localstack/localstack-pro:latest` and forwards the token. Pro is
        required for: {{resolve:secretsmanager:...}} dynamic refs, public
        Lambda layer fetching, reliable custom-resource Lambda callbacks.
        Pro license server enforces a minimum version (2026.3.0+); pinning
        to `:latest` keeps activation working.
      - Otherwise defaults to community `localstack/localstack:3.7` — last
        tag where SES is freely available before Pro gating mid-2024.
    """
    import os

    pro_token = os.environ.get("LOCALSTACK_AUTH_TOKEN")
    if image is None:
        image = (
            "localstack/localstack-pro:latest"
            if pro_token
            else "localstack/localstack:3.7"
        )
    container = LocalStackContainer(image=image).with_services(*services)
    if pro_token:
        # Reason: LocalStack Pro auth — forwarded as env so the token never
        # touches source files or fixture defaults.
        container.with_env("LOCALSTACK_AUTH_TOKEN", pro_token)
    if network is not None:
        container.with_network(network)
    if network_alias is not None:
        container.with_network_aliases(network_alias)
    if enable_lambda:
        # LocalStack spawns lambda runtimes as sibling containers via the
        # host docker daemon. Reason: docker-in-docker is slow and flaky;
        # sibling-container is the LocalStack-recommended pattern.
        container.with_volume_mapping("/var/run/docker.sock", "/var/run/docker.sock")
    with container as ls:
        url = ls.get_url()
        port = int(url.rsplit(":", 1)[-1])
        yield Container(host="localhost", port=port, url=url)


def seed_edp_manifest(localstack_url: str, manifest_path: Path) -> None:
    """Upload edp-module-assemblies/manifest.yaml + every asset it references.

    edp-api's ManifestService.from_client eagerly fetches the manifest at
    container boot. The pipeline (BomGenerator, DtmGenerator) then fetches
    every referenced bom.yaml, topology.yaml, spec.yaml when a job runs.
    Without all of these in the bucket, the job fails with NoSuchKey.

    Strategy: mirror the on-disk edp-module-assemblies repo into the bucket
    (real bytes for files that exist), then synthesize empty-but-valid stubs
    for any URL the manifest references that has no on-disk counterpart
    (plate specs are absent from the repo, for example).
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=localstack_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    s3.create_bucket(Bucket=EDP_MANIFEST_BUCKET)

    # 1. Manifest itself.
    s3.put_object(
        Bucket=EDP_MANIFEST_BUCKET,
        Key=EDP_MANIFEST_KEY,
        Body=manifest_path.read_bytes(),
    )

    # 2. Mirror everything on disk under the assemblies repo.
    repo_root = manifest_path.parent
    for path in repo_root.rglob("*"):
        if not path.is_file() or path == manifest_path:
            continue
        rel = path.relative_to(repo_root).as_posix()
        s3.put_object(Bucket=EDP_MANIFEST_BUCKET, Key=rel, Body=path.read_bytes())

    # 3. Synthesize stubs for URLs the manifest references but that don't
    #    exist on disk (plate specs/STEP/DXF are absent from the repo).
    _seed_referenced_url_stubs(s3, manifest_path)


def _seed_referenced_url_stubs(s3, manifest_path: Path) -> None:
    """For every s3:// URL in the manifest, ensure something is in the bucket.

    Tries HEAD first; only synthesizes if missing. Stub content is empty YAML
    (`{}` for spec/topology/bom — the generators tolerate empty parts/fields).
    """
    import yaml
    from botocore.exceptions import ClientError

    manifest = yaml.safe_load(manifest_path.read_text())
    for url in _walk_s3_urls(manifest):
        if not url.startswith(f"s3://{EDP_MANIFEST_BUCKET}/"):
            continue
        key = url.removeprefix(f"s3://{EDP_MANIFEST_BUCKET}/")
        try:
            s3.head_object(Bucket=EDP_MANIFEST_BUCKET, Key=key)
        except ClientError:
            s3.put_object(Bucket=EDP_MANIFEST_BUCKET, Key=key, Body=b"{}\n")


def _walk_s3_urls(node: object) -> Generator[str]:
    """Yield every string starting with `s3://` in a nested dict/list."""
    if isinstance(node, str):
        if node.startswith("s3://"):
            yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_s3_urls(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_s3_urls(v)


@contextmanager
def start_edp_api(
    image: str = "173.211.12.43:8083/library/edp-api:latest",
    port: int = 8000,
    network: Network | None = None,
    s3_endpoint_url: str | None = None,
) -> Generator[Container]:
    """Run the published edp-api image from the self-hosted Harbor registry.

    Default tag is `:latest` — what edp-api's CI publishes on every main merge.
    For a pinned local build, override with `image="edp-api:test"` after
    running `docker build -t edp-api:test ../edp-api`.

    `s3_endpoint_url` is forwarded to the container as S3_ENDPOINT_URL so
    edp-api's ManifestService.from_client targets LocalStack instead of
    real S3. Required: pair with `network=` + a LocalStack started on the
    same network with a known alias (e.g. 'localstack').
    """
    container = DockerContainer(image).with_exposed_ports(port).with_env("ENV", "beta")
    if network is not None:
        container.with_network(network)
    if s3_endpoint_url is not None:
        container.with_env("S3_ENDPOINT_URL", s3_endpoint_url)
        # Reason: boto3 needs *some* creds even for LocalStack.
        container.with_env("AWS_ACCESS_KEY_ID", "test")
        container.with_env("AWS_SECRET_ACCESS_KEY", "test")
    container.waiting_for(LogMessageWaitStrategy("Application startup complete"))
    with container as c:
        mapped = int(c.get_exposed_port(port))
        yield Container(
            host="localhost",
            port=mapped,
            url=f"http://localhost:{mapped}",
        )
