"""Structural tests for the per-variant docker-compose files.

We don't run the compose stack (would need real AWS / Tiger / Aura). We
do guarantee that:
  - both compose files parse as YAML cleanly
  - both declare hivemq + the broker-leg long-runners we expect
  - commercial additionally declares the analyst stack + its seed inits
  - init containers use restart: no, long-runners use restart: unless-stopped
  - all services consume split env files (config + secrets)
"""

from pathlib import Path

import pytest
import yaml

COMPOSE_DIR = Path(__file__).parent
COMMERCIAL_COMPOSE = COMPOSE_DIR / "commercial" / "docker-compose.yaml"
DEFENSE_COMPOSE = COMPOSE_DIR / "defense" / "docker-compose.yaml"
FIXTURES_COMPOSE = COMPOSE_DIR / "industrial-fixtures" / "docker-compose.yaml"

BROKER_LEG = (
    "hivemq",
    "device-api",
    "der-control-api",
    "telemetry-writer",
    "industrial-gateway",
    "hmi",
)
FIXTURE_SERVICES = (
    "mock-modbus-server",
    "mock-snmp-agent",
    "mock-redfish-service",
    "mock-dnp3-outstation",
    "mock-bacnet-device",
    "mock-bess-rack-1",
    "mock-bess-rack-2",
)
COMMERCIAL_INITS: tuple[str, ...] = ()
COMMERCIAL_ANALYST = ("analyst-server", "analyst-model")


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_compose_parses_and_declares_hivemq(variant_path: Path) -> None:
    """Both variants parse and ship the custom File-RBAC HiveMQ image with
    credentials.xml mounted into the extension's conf/ dir."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert — custom auth image (Allow-All stripped), not vanilla CE
    hivemq = spec["services"]["hivemq"]
    assert hivemq["image"] == "public.ecr.aws/y1d2j6a8/ems-hivemq:latest"
    assert any(
        "credentials.xml" in v and "hivemq-file-rbac-extension" in v
        for v in hivemq["volumes"]
    ), "credentials.xml must be mounted into the File RBAC extension"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_telemetry_writer_uses_baked_image_not_runtime_pip(
    variant_path: Path,
) -> None:
    """telemetry-writer must reference the ECR image (deps baked in), not
    python:3.13-alpine + runtime pip install.

    Reason: runtime `pip install paho-mqtt psycopg2-binary` 404s on
    pypi.org if the instance reboots offline → container restart-loops →
    telemetry ingest dies. Same image consumed by appliance (platform-
    ems-iso) — bug fix lands once, propagates everywhere.
    """
    # Arrange + Act
    svc = yaml.safe_load(variant_path.read_text())["services"]["telemetry-writer"]

    # Assert — ECR image is owned by platform-api's build_telemetry_writer
    # CI job; see src/compose/images/telemetry-writer/Dockerfile.
    assert svc["image"] == "public.ecr.aws/y1d2j6a8/ems-telemetry-writer:latest"
    assert "command" not in svc, "image has CMD baked in; no override needed"
    assert "volumes" not in svc, "script lives in image; no bind-mount needed"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_der_control_api_ships_internal_only(variant_path: Path) -> None:
    """ems-der-control-api ships on both variants: ECR image, ENV=beta, and NO
    published port — der-control-ingress is the only reachable path in.
    """
    # Arrange + Act
    svc = yaml.safe_load(variant_path.read_text())["services"]["der-control-api"]

    # Assert
    assert svc["image"] == "public.ecr.aws/y1d2j6a8/ems-der-control-api:latest"
    assert svc["environment"]["ENV"] == "beta"
    assert "ports" not in svc, "internal-only — der-control-ingress fronts it"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_der_control_ingress_terminates_mtls_in_front_of_der_control_api(
    variant_path: Path,
) -> None:
    """der-control-ingress is the only publicly reachable path to
    der-control-api: mutual-TLS terminator (IEEE 2030.5 requires client
    certs), published on 8443, never touching HMI's existing :80 path.
    """
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]
    svc = services["der-control-ingress"]

    # Assert — vanilla nginx, published mTLS port, depends on the app it fronts
    assert svc["image"] == "nginx:1.27-alpine"
    assert svc["ports"] == ["8443:8443"]
    assert "der-control-api" in svc["depends_on"]

    # Assert — cert/key/truststore/conf all bind-mounted read-only, nothing baked
    volumes = svc["volumes"]
    assert any(v.endswith(":/etc/nginx/tls/cert.pem:ro") for v in volumes)
    assert any(v.endswith(":/etc/nginx/tls/key.pem:ro") for v in volumes)
    assert any(v.endswith(":/etc/nginx/tls/truststore.pem:ro") for v in volumes)
    assert any(v.endswith(":/etc/nginx/conf.d/default.conf:ro") for v in volumes)



def test_defense_ships_broker_leg_plus_the_analyst_stack() -> None:
    """Defense ships the broker leg and the analyst stack, the same services as
    commercial. No init containers (consumers self-seed)."""
    # Arrange + Act
    services = yaml.safe_load(DEFENSE_COMPOSE.read_text())["services"]

    # Assert — broker leg + both analyst services present
    for svc in (*BROKER_LEG, *COMMERCIAL_ANALYST):
        assert svc in services, f"defense missing {svc}"
    # Assert — no init containers
    for absent in COMMERCIAL_INITS:
        assert absent not in services, f"defense should not ship {absent}"


def test_commercial_has_broker_plus_analyst_stack() -> None:
    """Commercial ships broker leg + analyst stack + matching seed inits."""
    # Arrange + Act
    services = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]

    # Assert
    for svc in (*BROKER_LEG, *COMMERCIAL_INITS, *COMMERCIAL_ANALYST):
        assert svc in services, f"commercial missing {svc}"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_no_variant_declares_industrial_fixtures(variant_path: Path) -> None:
    """Neither variant declares fixture services directly — system_adr §25:
    a real customer deployment ships every device unprovisioned and runs no
    fixtures. They only exist in the e2e-only overlay (FIXTURES_COMPOSE),
    merged in by UserData via a second `docker compose -f` when e2e=True.
    """
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]

    # Assert
    for fixture in FIXTURE_SERVICES:
        assert fixture not in services, f"{variant_path.name} ships {fixture}"


def test_fixtures_overlay_declares_every_fixture_and_gateway_dependency() -> None:
    """The overlay declares all 7 fixtures and adds them to industrial-gateway's
    depends_on — the two things a real deploy's compose files no longer have."""
    # Arrange + Act
    services = yaml.safe_load(FIXTURES_COMPOSE.read_text())["services"]

    # Assert — every fixture present
    for fixture in FIXTURE_SERVICES:
        assert fixture in services, f"fixtures overlay missing {fixture}"
    # Assert — industrial-gateway's partial def adds exactly the fixture deps
    gateway_deps = set(services["industrial-gateway"]["depends_on"].keys())
    assert gateway_deps == set(FIXTURE_SERVICES)


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_long_runners_have_unless_stopped(variant_path: Path) -> None:
    """Long-running services restart on EC2 reboot via the docker daemon."""
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]

    # Assert
    for svc in BROKER_LEG:
        assert (
            services[svc]["restart"] == "unless-stopped"
        ), f"{variant_path.name}: {svc} should be unless-stopped"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_all_services_consume_split_env_files(variant_path: Path) -> None:
    """Every service except mock-* protocol fixtures consumes both env files.

    Split surfaces the secret/non-secret distinction at the file level so
    operators can see which file holds what without running the container.
    Mocks are standalone protocol listeners — no env_file needed.
    """
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]

    # Assert
    for name, svc in services.items():
        if name.startswith("mock-"):
            continue  # protocol fixtures have no env config
        env_files = svc.get("env_file", [])
        assert (
            "/opt/arcnode/config.env" in env_files
        ), f"{variant_path.name}: {name} missing config.env"
        assert (
            "/opt/arcnode/secrets.env" in env_files
        ), f"{variant_path.name}: {name} missing secrets.env"


def test_analyst_model_runs_beta_stage_as_a_daily_daemon() -> None:
    """analyst-model reads its beta stage + the box's customer overlay, and
    runs --mode schedule so the container stays up for the daily job.

    Reason: the image defaults to --mode schedule now, but compose passes it
    anyway so a future default flip can't turn this into a run-once-and-exit loop.
    """
    # Arrange + Act
    service = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]["analyst-model"]

    # Assert
    assert service["environment"] == {
        "ENV": "beta",
        "CFG_CUSTOMER_PATH": "/app/cfg.customer.yml",
    }
    assert service["volumes"] == [
        "/opt/arcnode/analyst-model-cfg.customer.yml:/app/cfg.customer.yml:ro"
    ]
    assert service["command"] == ["uv", "run", "-m", "src.main", "--mode", "schedule"]


def test_analyst_server_points_at_itself_and_the_device_api() -> None:
    """The agent reads telemetry through the server in the same container and
    fetches the topology from the Device API on the compose network.

    Reason: the server listens on 0.0.0.0:8000 inside its container, so localhost
    reaches it. The Device API is its compose service name.
    """
    # Arrange + Act
    service = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]["analyst-server"]

    # Assert
    assert service["environment"]["SERVER_URL"] == "http://localhost:8000"
    assert service["environment"]["DEVICE_API_URL"] == "http://device-api:3000"
    assert service["environment"]["CFG_CUSTOMER_PATH"] == "/app/cfg.customer.yml"


def test_analyst_server_is_not_published_to_the_host() -> None:
    """The HMI reaches the analyst server over the compose network through its
    nginx, so no host port is needed.

    Reason: a published analyst port is an internet-facing chat API with no auth.
    """
    # Arrange + Act
    service = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]["analyst-server"]

    # Assert
    assert "ports" not in service


def test_hmi_is_only_reached_through_the_https_ingress() -> None:
    """Port 80 on the host is the https-ingress: it redirects to HTTPS and
    serves the Let's Encrypt challenge. The HMI publishes nothing.

    Reason: an operator must never see the HMI over plain HTTP.
    """
    # Arrange + Act
    services = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]

    # Assert
    assert "ports" not in services["hmi"]
    assert services["https-ingress"]["ports"] == ["80:80", "443:443"]


def test_der_control_api_reads_its_customer_config() -> None:
    """der-control-api merges its per-deployment keys (siteId, utilityMirrorUrl,
    publicBaseUrl) over its ENV block from a file mounted read-only."""
    # Arrange + Act
    service = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]["der-control-api"]

    # Assert
    assert service["environment"]["CFG_CUSTOMER_PATH"] == "/app/cfg.customer.yml"
    assert "/opt/arcnode/der-control-cfg.customer.yml:/app/cfg.customer.yml:ro" in service["volumes"]
