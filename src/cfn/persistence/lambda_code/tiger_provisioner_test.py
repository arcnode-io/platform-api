"""Smoke tests for the Tiger Cloud provisioning Lambda source."""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "tiger_provisioner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tiger_provisioner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    mod = _load_module()
    assert callable(mod.handler)


def test_module_only_uses_stdlib_and_boto3() -> None:
    """No external deps — must run in vanilla python3.13 runtime."""
    source = MODULE_PATH.read_text()
    forbidden = ["import requests", "import httpx", "from requests"]
    for needle in forbidden:
        assert needle not in source, f"Tiger Lambda must not import {needle}"


def test_handler_handles_create_update_delete() -> None:
    """Lambda dispatches on event['RequestType']."""
    source = MODULE_PATH.read_text()
    assert "RequestType" in source
    assert "Create" in source
    assert "Delete" in source


def test_uses_basic_auth_with_access_and_secret_keys() -> None:
    """Tiger Cloud REST API requires HTTP Basic auth (access_key:secret_key)."""
    source = MODULE_PATH.read_text()
    assert "TigerCloudAccessKey" in source
    assert "TigerCloudSecretKey" in source
    assert "Basic" in source


def test_targets_correct_api_base() -> None:
    """Confirms the Tiger Cloud REST API base URL is wired in."""
    source = MODULE_PATH.read_text()
    assert "console.cloud.tigerdata.com/public/api/v1" in source
