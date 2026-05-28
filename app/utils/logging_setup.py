from __future__ import annotations

import logging

_REDACTED_PLACEHOLDER = "[REDACTED]"


class APIKeyRedactionFilter(logging.Filter):
    """Redact the configured API key from log records before they are written."""

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__()
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""

    def set_api_key(self, api_key: str | None) -> None:
        """Update the API key used for redaction."""
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._api_key:
            return True

        api_key = self._api_key
        message = record.getMessage()
        if api_key in message:
            redacted = message.replace(api_key, _REDACTED_PLACEHOLDER)
            record.msg = redacted
            record.args = ()

        if record.exc_info:
            formatted_exception = logging.Formatter().formatException(record.exc_info)
            if api_key in formatted_exception:
                record.exc_text = formatted_exception.replace(api_key, _REDACTED_PLACEHOLDER)
        elif isinstance(record.exc_text, str) and api_key in record.exc_text:
            record.exc_text = record.exc_text.replace(api_key, _REDACTED_PLACEHOLDER)

        return True
