from __future__ import annotations

import logging
import unittest

from app.utils.logging_setup import APIKeyRedactionFilter, _REDACTED_PLACEHOLDER


class APIKeyRedactionFilterTests(unittest.TestCase):
    def test_filter_replaces_configured_api_key_in_message(self) -> None:
        redaction_filter = APIKeyRedactionFilter(api_key="sk-secret-key")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Request failed with key sk-secret-key attached",
            args=(),
            exc_info=None,
        )

        self.assertTrue(redaction_filter.filter(record))
        self.assertEqual(
            record.getMessage(),
            f"Request failed with key {_REDACTED_PLACEHOLDER} attached",
        )

    def test_filter_replaces_api_key_in_percent_formatted_args(self) -> None:
        redaction_filter = APIKeyRedactionFilter(api_key="sk-secret-key")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Request failed with key %s attached",
            args=("sk-secret-key",),
            exc_info=None,
        )

        self.assertTrue(redaction_filter.filter(record))
        self.assertEqual(
            record.getMessage(),
            f"Request failed with key {_REDACTED_PLACEHOLDER} attached",
        )

    def test_filter_leaves_message_unchanged_when_key_is_empty(self) -> None:
        redaction_filter = APIKeyRedactionFilter(api_key="")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Request failed with key sk-secret-key attached",
            args=(),
            exc_info=None,
        )

        self.assertTrue(redaction_filter.filter(record))
        self.assertEqual(record.getMessage(), "Request failed with key sk-secret-key attached")

    def test_set_api_key_updates_redaction_behavior(self) -> None:
        redaction_filter = APIKeyRedactionFilter()
        redaction_filter.set_api_key("sk-new-key")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Failure sk-new-key",
            args=(),
            exc_info=None,
        )

        self.assertTrue(redaction_filter.filter(record))
        self.assertEqual(record.getMessage(), f"Failure {_REDACTED_PLACEHOLDER}")

    def test_filter_replaces_api_key_in_exception_traceback_text(self) -> None:
        redaction_filter = APIKeyRedactionFilter(api_key="sk-secret-key")
        formatter = logging.Formatter("%(message)s")
        try:
            raise RuntimeError("API call failed for key sk-secret-key")
        except RuntimeError:
            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Request failed",
                args=(),
                exc_info=logging.sys.exc_info(),
            )

        self.assertTrue(redaction_filter.filter(record))
        formatted = formatter.format(record)
        self.assertNotIn("sk-secret-key", formatted)
        self.assertIn(_REDACTED_PLACEHOLDER, formatted)
