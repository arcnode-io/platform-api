"""Smoke tests for the Bedrock preflight Lambda source.

The function runs in Lambda; we test the parts that are pure Python:
module loads, handler is callable, model IDs are exactly the ones the
EC2 IAM policy permits, error message contains the actionable AWS
console path.
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


def test_probe_targets_match_iam_policy() -> None:
    """Model IDs must match the EC2 + preflight IAM policy verbatim.

    A drift here is a silent bug — the preflight passes, then runtime
    fails on a different model id.
    """
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert mod.TITAN_MODEL == "amazon.titan-embed-text-v2:0"
    assert mod.CLAUDE_PROFILE == "us.anthropic.claude-sonnet-4-6"


def test_access_denied_message_includes_console_path() -> None:
    """Error must tell operators exactly where to click to fix it."""
    # Arrange + Act
    mod = _load_module()
    msg = mod._access_denied_message("amazon.titan-embed-text-v2:0")

    # Assert
    assert "amazon.titan-embed-text-v2:0" in msg
    assert "Bedrock" in msg
    assert "Model access" in msg
