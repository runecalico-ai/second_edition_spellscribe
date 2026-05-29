# File Logging — Application Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `setup_logging()` utility into the SpellScribe GUI so frozen Windows builds capture WARNING+ errors to disk, redact the runtime API key, and expose an “Open Logs Folder” toolbar action.

**Architecture:** Call `setup_logging()` once in the `main_window.py` `__main__` block immediately after `AppConfig.load()`, retaining the returned `LoggingSetupResult` at module scope for the process lifetime. Pass the resolved runtime API key (env → plaintext config → keyring, matching extraction) into the redaction filter at startup and refresh it after a successful Settings save. Add a toolbar action (not a Help menu — the app has no `menuBar`) that opens `%APPDATA%\SpellScribe\logs` via `os.startfile`. Existing `_LOGGER.error(...)` in `_on_worker_failed` becomes the first real consumer once the root file handler is attached.

**Tech Stack:** Python 3.12, PySide6, stdlib `logging`, Windows `os.startfile`, unittest + `unittest.mock`.

---

## Spec Guardrails

| Requirement | Plan coverage |
|-------------|---------------|
| Persistent log + `error.old.log` rotation on startup | Task 1 (`setup_logging` at launch — already implemented in utility) |
| Multi-instance numbered logs | Task 1 (utility; verified manually in OpenSpec §3.3) |
| UTC timestamp, thread name, logger name, level, message | Task 4 (integration test asserts format via worker failure) |
| API key redaction | Tasks 1–2 (`_resolve_api_key_for_redaction` + `set_api_key` after settings) |
| User can open logs folder | Task 3 (toolbar action + test) |

**Intentionally out of scope (separate OpenSpec §3 manual verification):** two-instance manual test, Explorer UI confirmation.

**Intentionally out of scope (not in tasks.md §2):** `extract_cli.py` logging, in-app log viewer, MenuBar/Help menu introduction.

## Prerequisites: What Already Exists

- `app/utils/logging_setup.py` — `setup_logging()`, `APIKeyRedactionFilter`, `LoggingSetupResult` (Windows byte-lock claim).
- `app/paths.py` — `spellscribe_logs_dir()` → `%APPDATA%\SpellScribe\logs` (no `mkdir` until claim).
- `tests/test_logging_setup.py`, `tests/test_paths.py` — utility-layer coverage.
- `app/ui/main_window.py` — toolbar-only UI; `_LOGGER.error` at worker failure (line ~670); `__main__` loads config then shows window (lines 825–834).
- `app/pipeline/extraction.py` — `_resolve_anthropic_api_key(config)` with full precedence tests in `tests/test_pipeline_extraction.py::APIKeyResolutionTests`.

## Resolved Design Decisions (Grill-Me Outcomes)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Toolbar vs Help menu for “Open Logs Folder”? | **Toolbar action** after Settings separator | `design.md` §5; app has no `menuBar()` today (`tasks.md` / `proposal.md` text is stale). |
| Where to store `LoggingSetupResult`? | **Module-level `_app_logging_setup`** in `main_window.py` | Keeps claim handle alive for process lifetime; window reads filter via helper. |
| Which API key for redaction? | **`_resolve_anthropic_api_key` wrapped to return `""` on failure** | Must redact env/keyring keys, not only `config.api_key` plaintext field. |
| Sync redaction after settings? | **Only when `SettingsDialog.exec()` returns `Accepted`** | Save path calls `accept()`; cancel must not change filter. |
| `setup_logging()` failure (100 locked files)? | **Non-fatal:** catch `RuntimeError`, show `QMessageBox.warning`, continue without file logging | Extremely rare; app must remain usable for support scenarios. |
| Disable “Open Logs” during workers? | **No — always enabled** | Read-only filesystem action; unlike Settings. |
| `extract_cli.py` logging? | **Deferred** | Not listed in OpenSpec tasks §2. |

## File Map

- Modify: `app/ui/main_window.py` — logging init, redaction sync, toolbar action, helpers.
- Modify: `tests/test_ui_main_window.py` — toolbar assertion update + new logging integration tests.
- Optional doc sync: `openspec/changes/add-file-logging/tasks.md` (change 2.2 wording from Help menu → toolbar).

---

### Task 1: Add Logging Helpers and Module State

**Files:**
- Modify: `app/ui/main_window.py` (imports + module-level state + helpers, before `SpellScribeMainWindow`)

- [ ] **Step 1: Write the failing helper tests**

Add to `tests/test_ui_main_window.py`:

```python
from contextlib import suppress

from app.config import AppConfig


class TestMainWindowLoggingHelpers(unittest.TestCase):
  def test_resolve_api_key_for_redaction_returns_empty_when_unconfigured(self) -> None:
      from app.ui.main_window import _resolve_api_key_for_redaction

      with patch.dict("os.environ", {}, clear=True):
          resolved = _resolve_api_key_for_redaction(
              AppConfig(api_key_storage_mode="env", api_key="")
          )
      self.assertEqual(resolved, "")

  def test_resolve_api_key_for_redaction_uses_env_var(self) -> None:
      from app.ui.main_window import _resolve_api_key_for_redaction

      with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-env"}, clear=True):
          resolved = _resolve_api_key_for_redaction(
              AppConfig(api_key_storage_mode="credential_manager", api_key="")
          )
      self.assertEqual(resolved, "sk-test-env")

  def test_sync_logging_redaction_updates_filter(self) -> None:
      from app.ui.main_window import _app_logging_setup, _init_app_logging, _sync_logging_redaction_from_config

      if _app_logging_setup is not None:
          self.skipTest("logging already initialized in this process")

      with tempfile.TemporaryDirectory() as tmp_dir:
          logs_dir = Path(tmp_dir)
          _init_app_logging(AppConfig(api_key_storage_mode="env", api_key=""), logs_dir=logs_dir)
          try:
              with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-new"}, clear=True):
                  _sync_logging_redaction_from_config(
                      AppConfig(api_key_storage_mode="env", api_key="")
                  )
              self.assertEqual(_app_logging_setup.redaction_filter._api_key, "sk-new")
          finally:
              from tests.test_logging_setup import SetupLoggingTests

              SetupLoggingTests()._release_logging()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowLoggingHelpers -v`

Expected: FAIL with `ImportError` / `AttributeError` for `_resolve_api_key_for_redaction`.

- [ ] **Step 3: Implement helpers in `main_window.py`**

Add imports near top of `app/ui/main_window.py`:

```python
import os
import sys
from contextlib import suppress

from app.paths import spellscribe_logs_dir
from app.utils.logging_setup import LoggingSetupResult, setup_logging
```

Add module state and helpers **after** `_LOGGER = logging.getLogger(__name__)`:

```python
_app_logging_setup: LoggingSetupResult | None = None


def _resolve_api_key_for_redaction(config: AppConfig) -> str:
    """Return the runtime API key string for log redaction, or '' if unavailable."""
    from app.pipeline.extraction import _resolve_anthropic_api_key

    with suppress(RuntimeError):
        return _resolve_anthropic_api_key(config)
    return ""


def _init_app_logging(
    config: AppConfig,
    *,
    logs_dir: Path | None = None,
) -> LoggingSetupResult | None:
    """Configure process-wide file logging; return None if claim fails."""
    global _app_logging_setup
    try:
        _app_logging_setup = setup_logging(
            logs_dir=logs_dir,
            api_key=_resolve_api_key_for_redaction(config),
        )
    except RuntimeError:
        _app_logging_setup = None
        return None
    return _app_logging_setup


def _sync_logging_redaction_from_config(config: AppConfig) -> None:
    if _app_logging_setup is None:
        return
    _app_logging_setup.redaction_filter.set_api_key(
        _resolve_api_key_for_redaction(config)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowLoggingHelpers -v`

Expected: PASS (Windows required for `_init_app_logging` path; skip or run on win32 only — add `@unittest.skipUnless(sys.platform == "win32", ...)` to the sync test if needed).

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py tests/test_ui_main_window.py
git commit -m "feat(ui): add file-logging helpers for main window integration"
```

---

### Task 2: Initialize Logging at GUI Entry Point

**Files:**
- Modify: `app/ui/main_window.py` (new `_run_gui()`, thin `__main__` block)

- [ ] **Step 1: Write the failing `_run_gui` test**

Add to `tests/test_ui_main_window.py`:

```python
class TestMainWindowRunGui(unittest.TestCase):
    def test_run_gui_initializes_logging_before_window(self) -> None:
        import app.ui.main_window as main_window_module

        config = AppConfig(api_key_storage_mode="env", api_key="")
        with (
            patch.object(main_window_module, "QApplication") as mock_app_cls,
            patch.object(main_window_module, "AppConfig") as mock_config_cls,
            patch.object(main_window_module, "_init_app_logging") as mock_init_logging,
            patch.object(main_window_module, "SpellScribeMainWindow") as mock_window_cls,
        ):
            mock_config_cls.load.return_value = config
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app
            mock_app.exec.return_value = 0
            mock_init_logging.return_value = MagicMock()
            mock_window = MagicMock()
            mock_window_cls.return_value = mock_window

            exit_code = main_window_module._run_gui(["spellscribe-test"])

            self.assertEqual(exit_code, 0)
            mock_config_cls.load.assert_called_once()
            mock_init_logging.assert_called_once_with(config, logs_dir=None)
            mock_window_cls.assert_called_once_with(config=config)
            mock_window.show.assert_called_once()
            mock_app.exec.assert_called_once()

    def test_run_gui_shows_warning_when_logging_init_fails(self) -> None:
        import app.ui.main_window as main_window_module

        config = AppConfig(api_key_storage_mode="env", api_key="")
        with (
            patch.object(main_window_module, "QApplication") as mock_app_cls,
            patch.object(main_window_module, "AppConfig") as mock_config_cls,
            patch.object(main_window_module, "_init_app_logging", return_value=None),
            patch.object(main_window_module, "SpellScribeMainWindow") as mock_window_cls,
            patch.object(main_window_module, "QMessageBox") as mock_msgbox,
        ):
            mock_config_cls.load.return_value = config
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app
            mock_app.exec.return_value = 0
            mock_window_cls.return_value = MagicMock()

            main_window_module._run_gui(["spellscribe-test"])

            mock_msgbox.warning.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowRunGui -v`

Expected: FAIL — `AttributeError: module has no attribute '_run_gui'`.

- [ ] **Step 3: Add `_run_gui()` and thin `__main__`**

Add before `if __name__ == "__main__":` in `app/ui/main_window.py`:

```python
def _run_gui(argv: list[str] | None = None) -> int:
    """Create the Qt application, initialize logging, and run the event loop."""
    import sys
    from PySide6.QtWidgets import QApplication

    qt_argv = list(argv) if argv is not None else sys.argv
    app = QApplication(qt_argv)
    config = AppConfig.load()
    if _init_app_logging(config) is None:
        QMessageBox.warning(
            None,
            "SpellScribe Logging",
            "Could not open a log file in the SpellScribe logs folder. "
            "The app will continue, but errors may not be saved to disk.",
        )
    window = SpellScribeMainWindow(config=config)
    window.resize(1200, 800)
    window.show()
    return app.exec()
```

Replace `if __name__ == "__main__":` with:

```python
if __name__ == "__main__":
    import sys

    sys.exit(_run_gui())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowRunGui -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py tests/test_ui_main_window.py
git commit -m "feat(ui): initialize file logging at GUI startup"
```

---

### Task 3: Add “Open Logs Folder” Toolbar Action

**Files:**
- Modify: `app/ui/main_window.py` (`_build_toolbar`, new `_on_open_logs_folder`)
- Modify: `tests/test_ui_main_window.py`

- [ ] **Step 1: Write the failing toolbar and handler tests**

Update `test_toolbar_has_expected_actions` expected tuple to include `"Open Logs Folder"`.

Add:

```python
class TestMainWindowOpenLogsFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_window(self):
        from app.ui.main_window import SpellScribeMainWindow

        return SpellScribeMainWindow(config=MagicMock())

    @patch("app.ui.main_window.os.startfile")
    def test_open_logs_folder_starts_explorer_at_logs_dir(self, mock_startfile) -> None:
        from app.ui.main_window import SpellScribeMainWindow

        logs_dir = Path("C:/Users/Test/AppData/Roaming/SpellScribe/logs")
        win = SpellScribeMainWindow(config=MagicMock())
        with patch("app.ui.main_window.spellscribe_logs_dir", return_value=logs_dir):
            win._on_open_logs_folder()
        mock_startfile.assert_called_once_with(os.fspath(logs_dir))

    @patch("app.ui.main_window.os.startfile", side_effect=OSError("access denied"))
    def test_open_logs_folder_shows_error_when_startfile_fails(self, _mock_startfile) -> None:
        from app.ui.main_window import SpellScribeMainWindow

        win = SpellScribeMainWindow(config=MagicMock())
        with (
            patch("app.ui.main_window.spellscribe_logs_dir", return_value=Path("C:/logs")),
            patch.object(win, QMessageBox.__name__, wraps=QMessageBox) as _,
            patch("app.ui.main_window.QMessageBox.critical") as mock_critical,
        ):
            win._on_open_logs_folder()
        mock_critical.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowOpenLogsFolder tests.test_ui_main_window.TestMainWindowToolbar.test_toolbar_has_expected_actions -v`

Expected: FAIL — missing action / missing method.

- [ ] **Step 3: Implement toolbar action**

In `_build_toolbar`, after Settings action (lines ~100–101):

```python
        tb.addSeparator()

        self._action_open_logs = tb.addAction("Open Logs Folder")
        self._action_open_logs.setToolTip(
            "Open the SpellScribe logs folder in File Explorer."
        )
        self._action_open_logs.triggered.connect(self._on_open_logs_folder)
```

Add handler on `SpellScribeMainWindow`:

```python
    def _on_open_logs_folder(self) -> None:
        logs_dir = spellscribe_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(os.fspath(logs_dir))
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Open Logs Folder",
                f"Could not open the logs folder:\n{exc}",
            )
```

Do **not** add `_action_open_logs` to `_update_action_states` — it stays enabled always.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowOpenLogsFolder tests.test_ui_main_window.TestMainWindowToolbar -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py tests/test_ui_main_window.py
git commit -m "feat(ui): add Open Logs Folder toolbar action"
```

---

### Task 4: Sync API Key Redaction After Settings Save

**Files:**
- Modify: `app/ui/main_window.py` (`_on_settings`)
- Modify: `tests/test_ui_main_window.py`

- [ ] **Step 1: Write the failing settings-sync test**

```python
class TestMainWindowLoggingSettingsSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    @patch("app.ui.main_window._sync_logging_redaction_from_config")
    @patch("app.ui.main_window.SettingsDialog")
    def test_settings_accepted_syncs_redaction_filter(
        self, mock_dlg_cls, mock_sync
    ) -> None:
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        win = SpellScribeMainWindow(config=config)
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = int(QDialog.DialogCode.Accepted)
        mock_dlg_cls.return_value = mock_dlg

        win._on_settings()

        mock_sync.assert_called_once_with(config)

    @patch("app.ui.main_window._sync_logging_redaction_from_config")
    @patch("app.ui.main_window.SettingsDialog")
    def test_settings_cancelled_does_not_sync_redaction(
        self, mock_dlg_cls, mock_sync
    ) -> None:
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        win = SpellScribeMainWindow(config=config)
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = int(QDialog.DialogCode.Rejected)
        mock_dlg_cls.return_value = mock_dlg

        win._on_settings()

        mock_sync.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowLoggingSettingsSync -v`

Expected: FAIL — `_sync_logging_redaction_from_config` not called.

- [ ] **Step 3: Update `_on_settings`**

```python
    def _on_settings(self) -> None:
        dlg = SettingsDialog(config=self._config, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _sync_logging_redaction_from_config(self._config)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowLoggingSettingsSync -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py tests/test_ui_main_window.py
git commit -m "feat(ui): refresh log redaction key after settings save"
```

---

### Task 5: End-to-End Worker Error Writes to Log File

**Files:**
- Modify: `tests/test_ui_main_window.py`

- [ ] **Step 1: Write the failing integration test**

Reuse read pattern from `tests/test_logging_setup.py`:

```python
def _read_active_log_file(result: LoggingSetupResult) -> str:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.acquire()
            try:
                handler.flush()
            finally:
                handler.release()
    result._claim_handle.flush()
    result._claim_handle.seek(0)
    return result._claim_handle.read()


@unittest.skipUnless(sys.platform == "win32", "file logging claim requires Windows")
class TestMainWindowWorkerLoggingIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def setUp(self) -> None:
        from app.ui import main_window as main_window_module

        self._module = main_window_module
        self._prior_setup = main_window_module._app_logging_setup

    def tearDown(self) -> None:
        from tests.test_logging_setup import SetupLoggingTests

        SetupLoggingTests()._release_logging()
        self._module._app_logging_setup = self._prior_setup

    def test_worker_failed_writes_warning_to_claimed_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            result = self._module._init_app_logging(
                AppConfig(api_key_storage_mode="env", api_key=""),
                logs_dir=logs_dir,
            )
            self.assertIsNotNone(result)

            win = self._module.SpellScribeMainWindow(config=MagicMock())
            with patch.object(win, QMessageBox.__name__):
                win._on_worker_failed("Detect Spells", "network timeout")

            contents = _read_active_log_file(result)  # type: ignore[arg-type]
            self.assertIn("Worker failed", contents)
            self.assertIn("Detect Spells", contents)
            self.assertIn("app.ui.main_window", contents)
```

- [ ] **Step 2: Run test to verify it fails (if logging not wired) or passes (if already wired)**

Run: `python -m unittest tests.test_ui_main_window.TestMainWindowWorkerLoggingIntegration -v`

Expected before Task 1–2 complete: FAIL (empty log). After startup wiring: PASS.

- [ ] **Step 3: No production code change if Task 1–2 already landed** — this test validates existing `_LOGGER.error` path.

- [ ] **Step 4: Run full targeted suite**

Run:

```pwsh
python -m unittest tests.test_ui_main_window.TestMainWindowLoggingHelpers tests.test_ui_main_window.TestMainWindowLoggingStartup tests.test_ui_main_window.TestMainWindowOpenLogsFolder tests.test_ui_main_window.TestMainWindowLoggingSettingsSync tests.test_ui_main_window.TestMainWindowWorkerLoggingIntegration tests.test_ui_main_window.TestMainWindowToolbar -v
```

Expected: all PASS on Windows.

- [ ] **Step 5: Run full test suite**

Run: `python -m unittest discover tests/ -v`

Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add tests/test_ui_main_window.py
git commit -m "test(ui): cover worker errors writing to file log"
```

---

### Task 6 (Optional): Align OpenSpec Task Wording

**Files:**
- Modify: `openspec/changes/add-file-logging/tasks.md`

- [ ] **Step 1: Update task 2.2 text**

Change:
`- [ ] 2.2 Add "Help > Open Logs Folder" menu action to SpellScribeMainWindow.`

To:
`- [ ] 2.2 Add "Open Logs Folder" toolbar action to SpellScribeMainWindow.`

- [ ] **Step 2: Commit**

```bash
git add openspec/changes/add-file-logging/tasks.md
git commit -m "docs(openspec): align open-logs task with toolbar UI"
```

---

## Manual Verification Checklist (OpenSpec §3)

After all tasks, on Windows with a dev or frozen build:

- [ ] Launch app → confirm `%APPDATA%\SpellScribe\logs\error.log` created.
- [ ] Trigger a worker failure (e.g. invaild API key + Detect) → confirm line in `error.log` with thread name `DetectWorker` or similar.
- [ ] Restart app → prior `error.log` renamed to `error.old.log`.
- [ ] Launch two instances → second uses `error.1.log`.
- [ ] Configure plaintext API key, log a message containing it → file shows `[REDACTED]`.
- [ ] Click **Open Logs Folder** → Explorer opens logs directory.

---

## Grill-Me Self-Review (Final Pass — ≥95% Confidence)

| Branch | Status |
|--------|--------|
| UI surface for open logs | ✅ Toolbar (matches codebase reality + design.md) |
| Startup ordering | ✅ `AppConfig.load` → `_init_app_logging` → window |
| Claim handle lifetime | ✅ Module-global `_app_logging_setup` |
| API key source | ✅ Reuses extraction resolver, non-throwing wrapper |
| Settings mutation path | ✅ In-place config update + sync on Accepted |
| Failure modes | ✅ `startfile` error dialog; logging claim warning |
| Test strategy | ✅ Unit + integration; win32 skips where needed |
| Spec gaps | ✅ All §2 tasks mapped; §3 remains manual |

**Assumptions accepted:** Windows-only desktop target; importing `_resolve_anthropic_api_key` from extraction in UI is acceptable short-term coupling.

**Resolved in plan:** `_run_gui()` extracted up front for testable startup ordering (avoids brittle `exec` of `__main__`).
