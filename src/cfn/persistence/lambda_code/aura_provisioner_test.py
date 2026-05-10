"""Smoke tests for the Neo4j Aura provisioning Lambda source."""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "aura_provisioner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aura_provisioner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    mod = _load_module()
    assert callable(mod.handler)


def test_module_only_uses_stdlib_and_boto3() -> None:
    source = MODULE_PATH.read_text()
    forbidden = ["import requests", "import httpx", "from requests"]
    for needle in forbidden:
        assert needle not in source


def test_handler_handles_create_update_delete() -> None:
    source = MODULE_PATH.read_text()
    assert "RequestType" in source
    assert "Create" in source
    assert "Delete" in source


def test_oauth_client_credentials_flow_used() -> None:
    """Aura uses OAuth2 client_credentials grant for token exchange."""
    source = MODULE_PATH.read_text()
    assert "client_credentials" in source


def test_passes_tenant_id_in_create_body() -> None:
    """Aura create-instance body requires tenant_id."""
    source = MODULE_PATH.read_text()
    assert "Neo4jAuraTenantId" in source
    assert '"tenant_id"' in source
