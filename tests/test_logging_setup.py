from __future__ import annotations

import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils.logging_setup import (
    APIKeyRedactionFilter,
    _REDACTED_PLACEHOLDER,
    _claim_log_file_path,
    _rotate_primary_log,
    _try_claim_log_file,
    setup_logging,
)


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


@unittest.skipUnless(sys.platform == "win32", "log file locking requires Windows msvcrt")
class LogRotationTests(unittest.TestCase):
    def test_rotate_primary_log_moves_error_log_to_old_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            error_log = logs_dir / "error.log"
            old_log = logs_dir / "error.old.log"
            error_log.write_text("session-a\n", encoding="utf-8")
            old_log.write_text("stale-backup\n", encoding="utf-8")

            _rotate_primary_log(error_log, old_log)

            self.assertFalse(error_log.exists())
            self.assertEqual(old_log.read_text(encoding="utf-8"), "session-a\n")

    def test_rotate_primary_log_is_noop_when_error_log_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            error_log = logs_dir / "error.log"
            old_log = logs_dir / "error.old.log"

            _rotate_primary_log(error_log, old_log)

            self.assertFalse(old_log.exists())

    def test_rotate_primary_log_keeps_existing_backup_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            error_log = logs_dir / "error.log"
            old_log = logs_dir / "error.old.log"
            error_log.write_text("new-session\n", encoding="utf-8")
            old_log.write_text("existing-backup\n", encoding="utf-8")

            with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
                _rotate_primary_log(error_log, old_log)

            self.assertTrue(error_log.exists())
            self.assertEqual(error_log.read_text(encoding="utf-8"), "new-session\n")
            self.assertEqual(old_log.read_text(encoding="utf-8"), "existing-backup\n")


@unittest.skipUnless(sys.platform == "win32", "log file locking requires Windows msvcrt")
class LogClaimTests(unittest.TestCase):
    def test_claim_log_file_path_returns_primary_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)

            claimed_path, claim_handle = _claim_log_file_path(logs_dir)
            claim_handle.close()

            self.assertEqual(claimed_path, logs_dir / "error.log")

    def test_claim_log_file_path_uses_numbered_suffix_when_primary_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            primary = logs_dir / "error.log"
            primary.write_text("", encoding="utf-8")

            with primary.open("a", encoding="utf-8") as held_handle:
                import msvcrt

                msvcrt.locking(held_handle.fileno(), msvcrt.LK_LOCK, 1)
                claimed_path, claim_handle = _claim_log_file_path(logs_dir)
                claim_handle.close()
                msvcrt.locking(held_handle.fileno(), msvcrt.LK_UNLCK, 1)

            self.assertEqual(claimed_path, logs_dir / "error.1.log")

    def test_claim_log_file_path_rotates_primary_before_claiming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            error_log = logs_dir / "error.log"
            error_log.write_text("previous-session\n", encoding="utf-8")

            claimed_path, claim_handle = _claim_log_file_path(logs_dir)
            claim_handle.close()

            self.assertEqual(claimed_path, error_log)
            self.assertEqual(
                (logs_dir / "error.old.log").read_text(encoding="utf-8"),
                "previous-session\n",
            )

    def test_try_claim_log_file_stays_exclusive_after_file_growth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            log_path = logs_dir / "error.log"
            log_path.write_text("seed\n", encoding="utf-8")

            first_claim_handle = _try_claim_log_file(log_path)
            self.assertIsNotNone(first_claim_handle)
            assert first_claim_handle is not None  # narrow type for static checkers

            try:
                first_claim_handle.write("grown\n")
                first_claim_handle.flush()

                second_claim_handle = _try_claim_log_file(log_path)
                self.assertIsNone(second_claim_handle)
            finally:
                first_claim_handle.close()


@unittest.skipUnless(sys.platform == "win32", "log file locking requires Windows msvcrt")
class SetupLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, logging.FileHandler):
                handler.close()
                root.removeHandler(handler)

    def test_setup_logging_creates_warning_level_file_with_utc_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            result = setup_logging(logs_dir=logs_dir)

            logger = logging.getLogger("tests.logging_setup")
            logger.warning("worker failed")

            contents = result.log_file_path.read_text(encoding="utf-8")
            self.assertRegex(
                contents,
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - MainThread - tests\.logging_setup - WARNING - worker failed\n$",
            )

    def test_setup_logging_skips_info_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            result = setup_logging(logs_dir=logs_dir)

            logging.getLogger("tests.logging_setup").info("ignored")

            self.assertEqual(result.log_file_path.read_text(encoding="utf-8"), "")

    def test_setup_logging_applies_redaction_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            result = setup_logging(logs_dir=logs_dir, api_key="sk-secret-key")

            logging.getLogger("tests.logging_setup").error("Failure sk-secret-key")

            contents = result.log_file_path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", contents)
            self.assertNotIn("sk-secret-key", contents)

    def test_setup_logging_records_background_thread_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            result = setup_logging(logs_dir=logs_dir)
            seen: list[str] = []

            def worker() -> None:
                logging.getLogger("tests.logging_setup").warning("background failure")
                seen.append(result.log_file_path.read_text(encoding="utf-8"))

            thread = threading.Thread(target=worker, name="DetectWorker")
            thread.start()
            thread.join(timeout=5)

            self.assertIn("DetectWorker", seen[0])

    def test_setup_logging_returns_result_that_keeps_claim_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            first = setup_logging(logs_dir=logs_dir)
            second = setup_logging(logs_dir=logs_dir)

            self.assertEqual(first.log_file_path, logs_dir / "error.log")
            self.assertEqual(second.log_file_path, logs_dir / "error.1.log")

            first._claim_handle.close()
            second._claim_handle.close()
