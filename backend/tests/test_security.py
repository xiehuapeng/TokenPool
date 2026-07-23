import logging

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.utils.redaction import SecretRedactionFilter, redact_secrets


def test_redaction_covers_bearer_and_sk_keys():
    value = (
        "Authorization: Bearer abc.def.ghi "
        "api_key=sk-provider-super-secret-value"
    )
    redacted = redact_secrets(value)
    assert "abc.def.ghi" not in redacted
    assert "provider-super-secret-value" not in redacted
    assert "REDACTED" in redacted


def test_log_filter_removes_secrets():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Bearer abc.def.ghi and sk-team-super-secret-value",
        (),
        None,
    )
    assert SecretRedactionFilter().filter(record)
    assert "abc.def.ghi" not in record.getMessage()
    assert "super-secret-value" not in record.getMessage()


def test_cors_wildcard_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            jwt_secret="j" * 32,
            api_key_pepper="p" * 32,
            cors_origins=["*"],
        )


def test_example_secrets_are_rejected():
    with pytest.raises(ValidationError):
        Settings(
            jwt_secret="replace-with-a-long-random-value",
            api_key_pepper="p" * 32,
            cors_origins=["http://localhost:5173"],
        )
