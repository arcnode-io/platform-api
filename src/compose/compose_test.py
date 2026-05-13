"""Structural tests for the per-variant docker-compose files.

We don't run the compose stack (would need real AWS / Tiger / Aura). We
do guarantee that:
  - both compose files parse as YAML cleanly
  - both declare the inits + long-runners we expect
  - long-runners gate behind the right inits via service_completed_successfully
  - emqx port 1883 is NOT exposed to the host (no auth → no public reach)
"""

from pathlib import Path

import pytest
import yaml

COMPOSE_DIR = Path(__file__).parent
COMMERCIAL_COMPOSE = COMPOSE_DIR / "commercial" / "docker-compose.yaml"
DEFENSE_COMPOSE = COMPOSE_DIR / "defense" / "docker-compose.yaml"


@pytest.mark.parametrize(
    ("variant_path", "expected_seed_graph_image"),
    [
        (COMMERCIAL_COMPOSE, "python:3.13-alpine"),
        (DEFENSE_COMPOSE, "python:3.13-alpine"),
    ],
)
def test_compose_yaml_parses_and_declares_emqx_plus_inits(
    variant_path: Path, expected_seed_graph_image: str
) -> None:
    """Both variants parse and carry the expected services."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert — services we always need
    services = spec["services"]
    for required in (
        "emqx",
        "emqx-rule-render",
        "seed-vector",
        "seed-timeseries",
        "seed-graph",
        "device-api",
        "industrial-gateway",
        "hmi",
        "analyst-api",
        "analyst-server",
        "analyst-agent",
        "analyst-model",
    ):
        assert required in services, f"{variant_path.name}: missing {required}"

    # Assert — seed-graph image differs by variant
    assert services["seed-graph"]["image"] == expected_seed_graph_image


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_emqx_waits_for_rule_render_to_complete(variant_path: Path) -> None:
    """emqx must DependsOn emqx-rule-render w/ service_completed_successfully."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert
    deps = spec["services"]["emqx"]["depends_on"]
    assert deps["emqx-rule-render"]["condition"] == "service_completed_successfully"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_emqx_does_not_publish_port_1883_to_host(variant_path: Path) -> None:
    """No-auth + internal-only — port 1883 stays on the compose bridge network."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert — emqx has no `ports:` block, OR no entry mapping 1883
    ports = spec["services"]["emqx"].get("ports", [])
    for p in ports:
        assert "1883" not in str(p), f"emqx port 1883 is exposed to host: {p}"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_init_containers_have_restart_no(variant_path: Path) -> None:
    """All init services explicitly restart: no — survives EC2 reboot without re-seeding."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert
    for init in ("emqx-rule-render", "seed-vector", "seed-timeseries", "seed-graph"):
        assert (
            spec["services"][init]["restart"] == "no"
        ), f"{variant_path.name}: {init} missing restart: no"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_long_runners_have_unless_stopped(variant_path: Path) -> None:
    """Long-running services restart on EC2 reboot via docker daemon."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert
    for service in (
        "emqx",
        "device-api",
        "industrial-gateway",
        "hmi",
        "analyst-api",
        "analyst-server",
        "analyst-agent",
        "analyst-model",
    ):
        assert spec["services"][service]["restart"] == "unless-stopped"


@pytest.mark.parametrize("variant_path", [COMMERCIAL_COMPOSE, DEFENSE_COMPOSE])
def test_all_services_consume_persistence_env(variant_path: Path) -> None:
    """Every service's env_file points at deployment.env + persistence.env."""
    # Arrange + Act
    spec = yaml.safe_load(variant_path.read_text())

    # Assert
    for name, svc in spec["services"].items():
        env_files = svc.get("env_file", [])
        assert (
            "/opt/arcnode/persistence.env" in env_files
        ), f"{variant_path.name}: {name} missing persistence.env"
        assert (
            "/opt/arcnode/deployment.env" in env_files
        ), f"{variant_path.name}: {name} missing deployment.env"
