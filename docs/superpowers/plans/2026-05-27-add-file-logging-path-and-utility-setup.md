# File Logging — Path and Utility Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the filesystem path resolver and logging utility module that back the `add-file-logging` OpenSpec change — persistent `%APPDATA%\SpellScribe\logs\error.log` storage with session rotation, multi-instance safety, UTC formatting, and API-key redaction primitives.

**Architecture:** Extend `app/paths.py` with a side-effect-free `spellscribe_logs_dir()` resolver matching existing data-dir conventions. Add `app/utils/logging_setup.py` with `APIKeyRedactionFilter` and `setup_logging()` that (1) lazily creates the logs directory, (2) rotates the primary `error.log` to `error.old.log` on startup, (3) claims a writable numbered log file using a Windows byte-lock held for process lifetime, and (4) attaches a single root `FileHandler` at WARNING+ with UTC timestamps and thread names. Application wiring (`main_window.py`, settings updates, UI menu) is intentionally deferred to the separate Application Integration plan.

**Tech Stack:** Python 3.12, stdlib `logging`, Windows `msvcrt` byte locking, unittest.

---

## Spec Guardrails

- Logs directory: `%APPDATA%\SpellScribe\logs\` (same user-writable root as config/session; never under PyInstaller `_MEIPASS`).
- Primary log file: `error.log`. On startup, if it exists, rename to `error.old.log` (overwrite any previous backup) before creating a new session log.
- Multi-instance: if primary `error.log` is already claimed by another process, try `error.1.log`, `error.2.log`, … up to `error.99.log`, then raise `RuntimeError`.
- Rotation applies only to the primary `error.log` path, not numbered suffix files (per design trade-off).
- Log level: WARNING and above only.
- Format: `%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s` with UTC `asctime`.
- API key redaction: replace configured key substrings with `[REDACTED]` before records reach the file handler.
- `setup_logging()` must accept an optional `logs_dir: Path | None = None` override for tests.
- `setup_logging()` returns a `LoggingSetupResult` exposing the active log path, the redaction filter, and a private claim handle that must stay alive for the process lifetime.

## Prerequisites: What Already Exists

- `spellscribe_data_dir()` in `app/paths.py` resolves `%APPDATA%\SpellScribe` with a Roaming fallback.
- `default_config_path()` / `default_session_path()` compose `spellscribe_data_dir() / filename` without creating directories.
- Config/session saves call `destination.parent.mkdir(parents=True, exist_ok=True)` at write time — logging follows the same lazy-create pattern inside `setup_logging()`.
- Only logging usage today: `_LOGGER.error(...)` in `app/ui/main_window.py` with no handlers configured (stderr last-resort only).
- Utility conventions in `app/utils/review_notes.py`: `from __future__ import annotations`, private `_`-prefixed helpers, Google-style docstrings, direct imports (no re-export from `__init__.py`).

## File Map

- Modify: `app/paths.py`
- Create: `app/utils/logging_setup.py`
- Modify: `tests/test_paths.py`
- Create: `tests/test_logging_setup.py`

## API Decisions Locked In By This Plan

- `spellscribe_logs_dir() -> Path` — returns `spellscribe_data_dir() / "logs"`; no `mkdir`.
- `APIKeyRedactionFilter(logging.Filter)` — constructed with optional initial key; exposes `set_api_key(key: str | None) -> None`.
- `LoggingSetupResult` frozen dataclass — fields: `log_file_path: Path`, `redaction_filter: APIKeyRedactionFilter`, `_claim_handle: TextIOWrapper` (leading underscore signals internal retention; callers should keep the result alive).
- `_claim_log_file_path(logs_dir: Path) -> tuple[Path, TextIOWrapper]` — rotates primary log, claims a numbered path, returns `(path, handle)` with an **held** `msvcrt` byte lock on the claim handle.
- `setup_logging(*, logs_dir: Path | None = None, api_key: str | None = None) -> LoggingSetupResult` — configures root logger; idempotent via clearing existing root `FileHandler` instances first. Callers must retain the returned result for the process lifetime so the claim lock stays active.

## Deferred to Application Integration (Out of Scope Here)

- Calling `setup_logging()` from `app/ui/main_window.py` `__main__` block.
- Updating the redaction filter after `AppConfig.load()` and on settings save (task 2.3 should pass the **resolved** runtime key — env var, keyring, or plaintext — not only `config.api_key`).
- Toolbar/menu "Open Logs Folder" action.
- Manual verification checklist in OpenSpec tasks §3.

---

### Task 1: Add Logs Directory Path Resolver

**Files:**
- Modify: `app/paths.py`
- Modify: `tests/test_paths.py`

- [x] **Step 1: Write the failing path tests**

Add to `tests/test_paths.py`:

```python
import os

from app.paths import spellscribe_data_dir, spellscribe_logs_dir


class SpellScribeLogsDirTests(unittest.TestCase):
    def test_spellscribe_logs_dir_resolves_under_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"APPDATA": tmp_dir}, clear=False):
                expected = Path(tmp_dir) / "SpellScribe" / "logs"
                self.assertEqual(spellscribe_logs_dir(), expected)

    def test_spellscribe_logs_dir_does_not_create_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"APPDATA": tmp_dir}, clear=False):
                logs_dir = spellscribe_logs_dir()
            self.assertFalse(logs_dir.exists())

    def test_spellscribe_logs_dir_uses_data_dir_helper(self) -> None:
        with patch("app.paths.spellscribe_data_dir", return_value=Path("C:/fake/SpellScribe")):
            self.assertEqual(spellscribe_logs_dir(), Path("C:/fake/SpellScribe/logs"))
```

- [x] **Step 2: Run path tests to verify they fail**

Run: `python -m unittest tests.test_paths.SpellScribeLogsDirTests -v`

Expected: FAIL with `ImportError` or `AttributeError: module 'app.paths' has no attribute 'spellscribe_logs_dir'`.

- [x] **Step 3: Implement `spellscribe_logs_dir()`**

Add to `app/paths.py` after `_APP_SUBDIR`:

```python
_LOGS_SUBDIR = "logs"


def spellscribe_logs_dir() -> Path:
    """Return the SpellScribe log directory under the application data folder."""
    return spellscribe_data_dir() / _LOGS_SUBDIR
```

- [x] **Step 4: Run path tests to verify they pass**

Run: `python -m unittest tests.test_paths -v`

Expected: PASS, including the three new tests.

- [x] **Step 5: Commit**

```bash
git add app/paths.py tests/test_paths.py
git commit -m "feat: resolve spellscribe logs directory path"
```

---

### Task 2: Add API Key Redaction Filter

**Files:**
- Create: `app/utils/logging_setup.py`
- Create: `tests/test_logging_setup.py`

- [x] **Step 1: Write the failing redaction tests**

Create `tests/test_logging_setup.py`:

```python
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
```

- [x] **Step 2: Run redaction tests to verify they fail**

Run: `python -m unittest tests.test_logging_setup.APIKeyRedactionFilterTests -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.logging_setup'`.

- [x] **Step 3: Implement `APIKeyRedactionFilter`**

Create `app/utils/logging_setup.py` with the filter portion:

```python
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

        message = record.getMessage()
        if self._api_key not in message:
            return True

        redacted = message.replace(self._api_key, _REDACTED_PLACEHOLDER)
        record.msg = redacted
        record.args = ()
        return True
```

- [x] **Step 4: Run redaction tests to verify they pass**

Run: `python -m unittest tests.test_logging_setup.APIKeyRedactionFilterTests -v`

Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add app/utils/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: add API key redaction logging filter"
```

---

### Task 3: Add Log Rotation and Multi-Instance Claim Helpers

**Files:**
- Modify: `app/utils/logging_setup.py`
- Modify: `tests/test_logging_setup.py`

- [x] **Step 1: Write the failing rotation and claim tests**

Append to `tests/test_logging_setup.py`:

```python
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.utils.logging_setup import _claim_log_file_path, _rotate_primary_log


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
```

- [x] **Step 2: Run rotation/claim tests to verify they fail**

Run: `python -m unittest tests.test_logging_setup.LogRotationTests tests.test_logging_setup.LogClaimTests -v`

Expected: FAIL with `ImportError` for `_rotate_primary_log` / `_claim_log_file_path`.

- [x] **Step 3: Implement rotation and claim helpers**

Add to `app/utils/logging_setup.py`:

```python
import msvcrt
import os
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path

_MAX_LOG_SUFFIX = 99
_PRIMARY_LOG_NAME = "error.log"
_OLD_LOG_NAME = "error.old.log"


def _rotate_primary_log(error_log: Path, old_log: Path) -> None:
    if not error_log.exists():
        return
    old_log.parent.mkdir(parents=True, exist_ok=True)
    if old_log.exists():
        old_log.unlink()
    error_log.replace(old_log)


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
```

- [x] **Step 4: Run rotation/claim tests to verify they pass**

Run: `python -m unittest tests.test_logging_setup.LogRotationTests tests.test_logging_setup.LogClaimTests -v`

Expected: PASS (5 tests).

Note: These tests require Windows (`msvcrt`). The project targets Windows only; CI/dev environments must run on Windows for this module.

- [x] **Step 5: Commit**

```bash
git add app/utils/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: add log rotation and multi-instance claim helpers"
```

---

### Task 4: Implement `setup_logging()` and End-to-End Handler Tests

**Files:**
- Modify: `app/utils/logging_setup.py`
- Modify: `tests/test_logging_setup.py`

- [x] **Step 1: Write the failing setup tests**

Append to `tests/test_logging_setup.py`:

```python
import logging
import sys
import threading
import tempfile

from app.utils.logging_setup import setup_logging


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
```

- [x] **Step 2: Run setup tests to verify they fail**

Run: `python -m unittest tests.test_logging_setup.SetupLoggingTests -v`

Expected: FAIL with `ImportError` for `setup_logging` / `LoggingSetupResult`.

- [x] **Step 3: Implement `setup_logging()`**

Add to `app/utils/logging_setup.py`:

```python
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class LoggingSetupResult:
    log_file_path: Path
    redaction_filter: APIKeyRedactionFilter
    _claim_handle: TextIOWrapper


def _utc_formatter() -> logging.Formatter:
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    formatter.converter = time.gmtime  # type: ignore[method-assign]
    return formatter


def _clear_root_file_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.FileHandler):
            handler.close()
            root.removeHandler(handler)


def setup_logging(*, logs_dir: Path | None = None, api_key: str | None = None) -> LoggingSetupResult:
    """Configure process-wide file logging for SpellScribe."""
    destination = logs_dir if logs_dir is not None else spellscribe_logs_dir()
    log_path, claim_handle = _claim_log_file_path(destination)

    _clear_root_file_handlers()

    redaction_filter = APIKeyRedactionFilter(api_key=api_key)
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(_utc_formatter())
    handler.addFilter(redaction_filter)

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.WARNING:
        root.setLevel(logging.WARNING)

    return LoggingSetupResult(
        log_file_path=log_path,
        redaction_filter=redaction_filter,
        _claim_handle=claim_handle,
    )
```

Also add the missing import at top of module:

```python
from app.paths import spellscribe_logs_dir
```

- [x] **Step 4: Run all logging setup tests to verify they pass**

Run: `python -m unittest tests.test_logging_setup -v`

Expected: PASS (all tests in module).

- [x] **Step 5: Run full test suite for regressions**

Run: `python -m unittest discover tests/ -v`

Expected: PASS (no regressions).

- [x] **Step 6: Commit**

```bash
git add app/utils/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: configure spellscribe file logging setup"
```

---

## Spec Coverage Map

| Spec requirement | Plan task |
|---|---|
| Logs under `%APPDATA%\SpellScribe\logs` | Task 1 (`spellscribe_logs_dir`) |
| Startup rotation `error.log` → `error.old.log` | Task 3 (`_rotate_primary_log`), exercised in Task 3/4 tests |
| Multi-instance numbered suffix files | Task 3 (`_claim_log_file_path`), Task 4 concurrent claim test |
| WARNING+ level | Task 4 (`setup_logging` handler level + root level) |
| UTC timestamp + thread + logger + level + message | Task 4 format test |
| API key → `[REDACTED]` | Task 2 filter + Task 4 integration test |
| User "Open Logs Folder" UI | Deferred (Application Integration plan) |
| `main_window.py` initialization | Deferred (Application Integration plan) |

## Grill-Me Decisions (Resolved)

| Decision | Resolution | Rationale |
|---|---|---|
| Logs path function name | `spellscribe_logs_dir()` | Matches `spellscribe_data_dir()`; `default_*_path()` reserved for file paths in this codebase |
| Lock mechanism | `msvcrt.LK_NBLCK` held on claim handle (not released until process exit) | Windows-only app; matches design "file locked" semantics without sidecar files |
| Claim API shape | `_claim_log_file_path` returns `(path, handle)` tuple | Avoids race between probe-close-reopen in separate calls |
| Which logger receives handler | Root logger | Ensures existing `_LOGGER.error(...)` calls across modules reach the file |
| Keep stderr handler in dev | No | Spec targets frozen EXE; file handler alone keeps behavior consistent |
| Redaction timing | `Filter.filter()` rewrites formatted message | Handles `%s` args used by existing worker error logging |
| Resolved vs raw config key at startup | Filter accepts `api_key=` param; wiring deferred | Task 2.3 must pass resolved runtime key, not only `config.api_key` |
| `setup_logging` idempotency | Clear existing root `FileHandler`s before add | Prevents duplicate lines if called twice in tests |
| Max suffix attempts | 99 (`error.99.log`) | Prevents infinite loop; raises clear `RuntimeError` |
| Rotation on numbered logs | Primary only | Explicit design trade-off |
| Export `_REDACTED_PLACEHOLDER` | Yes (module constant) | Enables precise unit assertions |

## Assumptions Accepted

- Development and CI test runs for `tests/test_logging_setup.py` execute on Windows (project target platform).
- Holding an `msvcrt` claim handle plus a separate `FileHandler` handle on the same path is acceptable on Windows for append-only logging.
- The Application Integration plan must store the `LoggingSetupResult` on the main window or module-level for the process lifetime (e.g. `_logging_setup: LoggingSetupResult | None`).
- Root logger configuration is process-global; CLI (`extract_cli.py`) logging integration remains out of scope until explicitly requested.

## Open Questions

- None blocking Path and Utility Setup implementation.

## Grill-Me Review Log

| Round | Question / finding | Resolution | Plan updated? |
|---|---|---|---|
| 1 | Logs path naming: `spellscribe_logs_dir()` vs `default_logs_dir()`? | `spellscribe_logs_dir()` — directory resolver, not a default file path | Yes |
| 1 | Where to `mkdir` the logs folder? | Inside `_claim_log_file_path`, not in path resolver | Yes |
| 1 | Which logger gets the file handler? | Root logger at WARNING+ | Yes |
| 2 | How to detect multi-instance lock without sidecar files? | Hold `msvcrt.LK_NBLCK` on a claim handle for process lifetime | Yes |
| 2 | **Bug:** claim helper unlocked before returning path | Return `(path, handle)` tuple; never unlock before retention | Yes |
| 2 | **Bug:** `setup_logging` claimed path twice (race window) | Single `_claim_log_file_path` returns both path and handle | Yes |
| 3 | Should tests run on non-Windows CI? | `@unittest.skipUnless(sys.platform == "win32")` on msvcrt tests | Yes |
| 3 | Task 2.3 passes `config.api_key` only — enough for env/keyring modes? | Deferred note: pass resolved runtime key | Yes |
| 3 | UI placement: toolbar (design) vs Help menu (tasks/spec)? | Deferred to Application Integration | Yes |
| 3 | Must caller retain `LoggingSetupResult`? | Yes — document in assumptions + integration deferred section | Yes |

**Satisfaction after round 3:** 96% — plan is ready for implementation. Remaining 4% is intentional deferral of application wiring and manual verification to the next plan/session, not ambiguity in Task 1 scope.
