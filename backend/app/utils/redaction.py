import logging
import re
from typing import Any


REDACTION_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b[a-fA-F0-9]{32}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r'(?i)(["\']?(?:api[_-]?key|token|secret|password)["\']?\s*[:=]\s*)'
        r'(["\']?)[^,\s}"\']+\2'
    ),
)


def redact_secrets(value: Any) -> str:
    text = str(value)
    text = REDACTION_PATTERNS[0].sub(r"\1***REDACTED***", text)
    text = REDACTION_PATTERNS[1].sub("sk-***REDACTED***", text)
    text = REDACTION_PATTERNS[2].sub("zhipu-***REDACTED***", text)
    text = REDACTION_PATTERNS[3].sub(r"\1***REDACTED***", text)
    return text


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def configure_secret_redaction() -> None:
    redaction_filter = SecretRedactionFilter()
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, SecretRedactionFilter) for item in logger.filters):
            logger.addFilter(redaction_filter)
        for handler in logger.handlers:
            if not any(
                isinstance(item, SecretRedactionFilter)
                for item in handler.filters
            ):
                handler.addFilter(redaction_filter)

    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_gateway_redaction_factory", False):
        return

    def redacting_factory(*args, **kwargs):
        record = current_factory(*args, **kwargs)
        redaction_filter.filter(record)
        return record

    redacting_factory._gateway_redaction_factory = True
    logging.setLogRecordFactory(redacting_factory)
