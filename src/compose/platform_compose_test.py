"""The platform compose (platform.arcnode.io): Caddy alone faces the internet,
platform-api and Postgres read their secrets from the box's env file."""

from pathlib import Path

import yaml

PLATFORM_COMPOSE: Path = Path(__file__).parent / "platform" / "docker-compose.yaml"
SECRETS_ENV: str = "/opt/arcnode-platform/secrets.env"


def test_platform_compose_runs_caddy_in_front_of_platform_api() -> None:
    # Arrange
    compose = yaml.safe_load(PLATFORM_COMPOSE.read_text())

    # Act
    services = compose["services"]

    # Assert
    assert set(services) == {"caddy", "platform-api", "edp-api", "postgres"}
    assert services["caddy"]["ports"] == ["80:80", "443:443"]
    assert all(
        "ports" not in services[s] for s in ("platform-api", "edp-api", "postgres")
    )
    assert services["platform-api"]["environment"]["ENV"] == "beta"
    assert services["edp-api"]["environment"]["ENV"] == "beta"
    assert SECRETS_ENV in services["platform-api"]["env_file"]
    assert SECRETS_ENV in services["postgres"]["env_file"]
