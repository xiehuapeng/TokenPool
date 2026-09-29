import logging

import pytest
from pydantic import ValidationError
from uvicorn.logging import AccessFormatter

from app.config.settings import Settings
from app.utils.redaction import (
    SecretRedactionFilter,
    configure_secret_redaction,
    redact_secrets,
)


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


def test_log_filter_redacts_formatted_arguments():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Authorization: Bearer %s",
        ("abc.def.ghi",),
        None,
    )
    assert SecretRedactionFilter().filter(record)
    assert record.args == ()
    assert "abc.def.ghi" not in record.getMessage()


def test_uvicorn_access_formatter_keeps_arguments_and_redacts_path():
    secret = "sk-team-super-secret-value"
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", f"/health?api_key={secret}", "1.1", 200),
        None,
    )
    redaction_filter = SecretRedactionFilter()
    # The record factory, logger and handler can each apply the filter.
    for _ in range(3):
        assert redaction_filter.filter(record)
    formatted = AccessFormatter(
        fmt='%(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    ).format(record)
    assert len(record.args) == 5
    assert record.args[4] == 200
    assert 'GET /health?api_key=' in formatted
    assert 'HTTP/1.1' in formatted
    assert '200' in formatted
    assert secret not in formatted
    assert 'REDACTED' in formatted


def test_uvicorn_access_record_factory_still_formats_without_secret():
    configure_secret_redaction()
    secret = "sk-team-another-secret-value"
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", f"/health?token={secret}", "1.1", 200),
        None,
    )
    formatted = AccessFormatter(
        fmt='%(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    ).format(record)
    assert "GET /health?token=" in formatted
    assert "200" in formatted
    assert secret not in formatted


@pytest.mark.asyncio
async def test_access_logger_remains_enabled_after_startup_migration(client):
    assert logging.getLogger("uvicorn.access").disabled is False
    response = await client.get("/health")
    assert response.status_code == 200


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
