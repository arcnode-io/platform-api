"""Smoke tests for the Bedrock preflight Lambda source.

The function runs in Lambda; we test the parts that are pure Python:
module loads, handler is callable, error message contains the actionable
AWS console path. The probe targets themselves are no longer hardcoded
in the Lambda — they're passed in via event.ResourceProperties — so the
"do model IDs match IAM" check has moved to bedrock_models_test.
"""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "bedrock_preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bedrock_preflight", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    """Lambda entry point must be ``handler(event, context)``."""
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert callable(mod.handler)


def test_probe_signature_takes_model_ids_via_kwargs() -> None:
    """_probe must accept chat_model_id + embed_model_id from the CR event."""
    # Arrange + Act
    mod = _load_module()

    # Assert — keyword-only signature so the CR can't silently swap them
    import inspect

    sig = inspect.signature(mod._probe)
    params = sig.parameters
    assert "chat_model_id" in params
    assert "embed_model_id" in params
    assert params["chat_model_id"].kind == inspect.Parameter.KEYWORD_ONLY


def test_access_denied_message_includes_console_path() -> None:
    """Error must tell operators exactly where to click to fix it."""
    # Arrange + Act
    mod = _load_module()
    msg = mod._access_denied_message("amazon.titan-embed-text-v2:0")

    # Assert
    assert "amazon.titan-embed-text-v2:0" in msg
    assert "Bedrock" in msg
    assert "Model access" in msg
