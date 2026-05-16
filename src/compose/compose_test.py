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

BROKER_LEG = (
    "hivemq",
    "device-api",
    "mock-modbus-server",
    "telemetry-writer",
    "industrial-gateway",
    "hmi",
)
COMMERCIAL_INITS: tuple[str, ...] = ()
COMMERCIAL_ANALYST = ("analyst-server", "analyst-model")


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_compose_parses_and_declares_hivemq(variant_path: Path) -> None:
    """Both variants parse and ship the HiveMQ CE broker."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert
    assert "hivemq" in spec["services"]
    assert spec["services"]["hivemq"]["image"].startswith("hivemq/hivemq-ce")


def test_defense_ships_broker_leg_plus_analyst_server() -> None:
    """Defense ships broker leg + analyst-server (Phase 1 smoke). No init
    containers (consumers self-seed). analyst-model lands in Phase 3."""
    # Arrange + Act
    services = yaml.safe_load(DEFENSE_COMPOSE.read_text())["services"]

    # Assert — broker leg + analyst-server present
    for svc in (*BROKER_LEG, "analyst-server"):
        assert svc in services, f"defense missing {svc}"
    # Assert — no init containers, no analyst-model yet
    for absent in (*COMMERCIAL_INITS, "analyst-model"):
        assert absent not in services, f"defense should not ship {absent}"


def test_commercial_has_broker_plus_analyst_stack() -> None:
    """Commercial ships broker leg + analyst stack + matching seed inits."""
    # Arrange + Act (mock-modbus-server is defense-only — strip from check)
    services = yaml.safe_load(COMMERCIAL_COMPOSE.read_text())["services"]

    # Assert
    for svc in (*BROKER_LEG, *COMMERCIAL_INITS, *COMMERCIAL_ANALYST):
        if svc == "mock-modbus-server":
            continue
        assert svc in services, f"commercial missing {svc}"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_long_runners_have_unless_stopped(variant_path: Path) -> None:
    """Long-running services restart on EC2 reboot via the docker daemon."""
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]

    # Assert
    for svc in BROKER_LEG:
        if svc not in services:
            # mock-modbus-server is defense-only, not in commercial
            continue
        assert (
            services[svc]["restart"] == "unless-stopped"
        ), f"{variant_path.name}: {svc} should be unless-stopped"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_all_services_consume_split_env_files(variant_path: Path) -> None:
    """Every service except mock-modbus-server consumes both env files.

    Split surfaces the secret/non-secret distinction at the file level so
    operators can see which file holds what without running the container.
    """
    # Arrange + Act
    services = yaml.safe_load(variant_path.read_text())["services"]

    # Assert
    for name, svc in services.items():
        if name == "mock-modbus-server":
            continue  # no env consumption
        env_files = svc.get("env_file", [])
        assert (
            "/opt/arcnode/config.env" in env_files
        ), f"{variant_path.name}: {name} missing config.env"
        assert (
            "/opt/arcnode/secrets.env" in env_files
        ), f"{variant_path.name}: {name} missing secrets.env"
