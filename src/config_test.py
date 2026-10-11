"""The log formatter keeps exception tracebacks. Without them a production failure
is one line with no cause (seen on platform.arcnode.io: "orchestrator failed" and
nothing else)."""

import logging
import sys

import pytest

from src.config import EmailProvider, _ZuluFormatter, load_config


def test_formatter_appends_the_traceback_when_the_record_carries_one() -> None:
    # Arrange
    formatter = _ZuluFormatter()
    record = _record_with_traceback()

    # Act
    actual = formatter.format(record)

    # Assert
    assert actual.startswith("20")
    assert "ERROR: orchestrator failed" in actual
    assert "Traceback (most recent call last)" in actual
    assert actual.endswith("RuntimeError: ses rejected the recipient")


def _reject_recipient() -> None:
    raise RuntimeError("ses rejected the recipient")


def _record_with_traceback() -> logging.LogRecord:
    """An ERROR record the way logging.exception() builds one: exc_info attached."""
    try:
        _reject_recipient()
    except RuntimeError:
        return logging.LogRecord(
            "orchestrator",
            logging.ERROR,
            __file__,
            1,
            "orchestrator failed",
            None,
            sys.exc_info(),
        )
    raise AssertionError("expected a RuntimeError")


def test_formatter_stays_one_line_without_an_exception() -> None:
    # Arrange
    formatter = _ZuluFormatter()
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "started", None, None)

    # Act
    actual = formatter.format(record)

    # Assert
    assert "\n" not in actual
    assert actual.endswith("  INFO: started")


def test_beta_sends_through_resend_and_local_through_localstack_ses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cfg.yml owns the switch: production (beta) uses Resend; local dev keeps LocalStack SES."""
    # Arrange
    monkeypatch.setenv("ENV", "beta")

    # Act
    beta = load_config()
    monkeypatch.setenv("ENV", "local")
    local = load_config()

    # Assert
    assert beta.email_provider == EmailProvider.RESEND
    assert local.email_provider == EmailProvider.SES
