from __future__ import annotations

import logging
import msvcrt
from io import TextIOWrapper
from pathlib import Path

_REDACTED_PLACEHOLDER = "[REDACTED]"
_MAX_LOG_SUFFIX = 99
_PRIMARY_LOG_NAME = "error.log"
_OLD_LOG_NAME = "error.old.log"


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


def _rotate_primary_log(error_log: Path, old_log: Path) -> None:
    if not error_log.exists():
        return
    old_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        error_log.replace(old_log)
    except OSError:
        # If another process already has the file open/locked, keep it in place
        # and let suffix-claiming choose the next available numbered log.
        return


def _log_file_name_for_suffix(index: int) -> str:
    if index == 0:
        return _PRIMARY_LOG_NAME
    return f"error.{index}.log"


def _try_claim_log_file(log_path: Path) -> TextIOWrapper | None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = log_path.open("a", encoding="utf-8")
    except OSError:
        return None

    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None

    return handle


def _claim_log_file_path(logs_dir: Path) -> tuple[Path, TextIOWrapper]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    primary_log = logs_dir / _PRIMARY_LOG_NAME
    _rotate_primary_log(primary_log, logs_dir / _OLD_LOG_NAME)

    for index in range(0, _MAX_LOG_SUFFIX + 1):
        candidate = logs_dir / _log_file_name_for_suffix(index)
        handle = _try_claim_log_file(candidate)
        if handle is not None:
            return candidate, handle

    raise RuntimeError(
        f"Could not claim a SpellScribe log file in {logs_dir} after {_MAX_LOG_SUFFIX + 1} attempts."
    )
