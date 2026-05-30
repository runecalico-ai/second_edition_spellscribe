# File Logging — Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close OpenSpec `add-file-logging` §3 Verification — prove log creation, rotation, multi-instance safety, API-key redaction, and the Open Logs Folder toolbar action match the spec and design, then mark tasks complete.

**Architecture:** Treat verification as a two-layer gate. Layer 1 runs the existing automated suite (utility + UI integration tests already map to 3.1–3.5). Layer 2 adds two targeted gap tests (subprocess restart rotation, worker-path redaction) and a Windows manual checklist for behaviors that cannot be faithfully simulated (real dual-GUI launch, real Explorer). Finish by updating `openspec/changes/add-file-logging/tasks.md` and producing a short verification report.

**Tech Stack:** Python 3.12, unittest, PySide6 (headless in tests), Windows `msvcrt` byte locks, manual Windows GUI checks.

**Prerequisites:** Tasks §1 (path + utility) and §2 (application integration) are implemented. Confirm with the prerequisite gate in Task 0 before starting §3 work.

---

## Spec ↔ Verification Mapping

| OpenSpec task | Spec scenario | Automated coverage today | Gap |
|---------------|---------------|--------------------------|-----|
| **3.1** Log creation + format (thread name) | Detailed Metadata | `SetupLoggingTests`, `TestMainWindowWorkerLoggingIntegration` | None critical |
| **3.2** `error.old.log` rotation on restart | Log Rotation on Startup | `LogRotationTests`, `LogClaimTests.test_claim_log_file_path_rotates_primary_before_claiming`, `LogRestartRotationTests` | Covered (cross-process restart test added Task 2) |
| **3.3** Multi-instance → `error.1.log` | Secondary Instance Logging | `LogClaimTests`, `SetupLoggingTests.test_setup_logging_returns_result_that_keeps_claim_alive` | No **two real GUI processes** test |
| **3.4** API key redaction in log file | API Key Redaction | `APIKeyRedactionFilterTests`, `test_setup_logging_applies_redaction_filter`, `test_worker_failed_redacts_api_key_in_log_file` | None critical (automated); manual pending Task 5 |
| **3.5** Open Logs Folder opens Explorer | Open Logs Folder | `TestMainWindowOpenLogsFolder` (mocked `startfile`) | Real Explorer not opened in CI |

## Design Guardrails (from `design.md`)

- Rotation applies only to primary `error.log`; secondary `error.N.log` files do not get `error.old.log` backups.
- If primary `error.log` is locked by another process, rotation is skipped (secondary instance logs to `error.1.log`).
- Log level: WARNING+ only; UTC timestamps; format `%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s`.
- Manual verification uses **dev** launch (`python -m app.ui.main_window`); note frozen-build smoke before release packaging.

## File Map

- Modify: `tests/test_logging_setup.py` — subprocess restart rotation test (Task 2).
- Modify: `tests/test_ui_main_window.py` — worker redaction integration test (Task 3).
- Modify: `openspec/changes/add-file-logging/tasks.md` — check off §3 (and §1–§2 if verified).
- Create: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md` — sign-off artifact (Task 6).

---

### Task 0: Prerequisite Gate — Confirm §1–§2 Implementation

**Files:**
- Read-only: `app/paths.py`, `app/utils/logging_setup.py`, `app/ui/main_window.py`
- Test: `tests/test_logging_setup.py`, `tests/test_paths.py`, `tests/test_ui_main_window.py`

- [x] **Step 1: Run logging-related unit tests**

```pwsh
cd c:\Users\vitki\OneDrive\GitHub\runecalico-ai\second_edition_spellscribe
. .\.venv\Scripts\Activate.ps1
python -m unittest tests.test_logging_setup tests.test_paths tests.test_ui_main_window -v
```

Expected: `OK` (1 skipped acceptable on non-win32 lock tests; on Windows expect 0 skips for lock tests).

- [x] **Step 2: Spot-check implementation exists**

Confirm these symbols exist (do not modify code in this task):

| Symbol | File |
|--------|------|
| `spellscribe_logs_dir()` | `app/paths.py` |
| `setup_logging()`, `APIKeyRedactionFilter` | `app/utils/logging_setup.py` |
| `_init_app_logging()`, `_run_gui()`, `_on_open_logs_folder()` | `app/ui/main_window.py` |
| Toolbar action `"Open Logs Folder"` | `app/ui/main_window.py` |

- [x] **Step 3: Abort if gate fails**

If any test fails or symbols are missing, stop — return to the Path/Utility or Application Integration plans first.

---

### Task 1: Automated Verification Audit (OpenSpec 3.1–3.5)

**Files:**
- Test: all files listed in Task 0

- [x] **Step 1: Run targeted test subsets and record mapping**

```pwsh
python -m unittest `
  tests.test_logging_setup.SetupLoggingTests `
  tests.test_logging_setup.LogRotationTests `
  tests.test_logging_setup.LogClaimTests `
  tests.test_logging_setup.APIKeyRedactionFilterTests `
  tests.test_logging_setup.LogRestartRotationTests `
  tests.test_ui_main_window.TestMainWindowOpenLogsFolder `
  tests.test_ui_main_window.TestMainWindowWorkerLoggingIntegration `
  -v
```

Expected: all PASS on Windows (22 tests after Task 2 adds `LogRestartRotationTests`).

- [x] **Step 2: Record audit results in verification report stub**

Create `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md`:

```markdown
# add-file-logging Verification Report

## Automated Audit (YYYY-MM-DD)

| Task | Result | Primary tests |
|------|--------|---------------|
| 3.1 | PASS/FAIL | SetupLoggingTests, TestMainWindowWorkerLoggingIntegration |
| 3.2 | PASS | LogRotationTests (in-process), LogClaimTests.test_claim_log_file_path_rotates_primary_before_claiming, LogRestartRotationTests.test_setup_logging_rotates_primary_log_across_process_restart |
| 3.3 | PARTIAL | LogClaimTests (simulated lock), SetupLoggingTests.test_setup_logging_returns_result_that_keeps_claim_alive; manual pending Task 5 |
| 3.4 | PASS | APIKeyRedactionFilterTests, SetupLoggingTests.test_setup_logging_applies_redaction_filter, TestMainWindowWorkerLoggingIntegration.test_worker_failed_redacts_api_key_in_log_file |
| 3.5 | PARTIAL | TestMainWindowOpenLogsFolder (mocked); manual pending Task 5 |
```

- [x] **Step 3: Commit audit stub** *(satisfied-by-artifact: verification report exists; operator may defer git commit)*

```bash
git add docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md
git commit -m "docs: start add-file-logging verification report"
```

**Note:** Commit may be deferred when the operator does not request a commit; record deferral in the verification report (see report **Note** on Task 1 Step 3).

---

### Task 2: Gap Test — Cross-Process Restart Rotation (OpenSpec 3.2)

**Files:**
- Modify: `tests/test_logging_setup.py`

**Rationale:** In-process rotation tests do not prove a **new process** renames the prior session's `error.log` to `error.old.log` after the first process exits and releases its lock.

- [x] **Step 1: Write the failing subprocess restart test**

Add imports at top of `tests/test_logging_setup.py` if missing:

```python
import subprocess
import textwrap
```

Add near the bottom of `tests/test_logging_setup.py`:

```python
@unittest.skipUnless(sys.platform == "win32", "log claim uses msvcrt on Windows")
class LogRestartRotationTests(unittest.TestCase):
    def test_setup_logging_rotates_primary_log_across_process_restart(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            prior_message = "session-one failure"

            first_script = textwrap.dedent(
                f"""
                import logging
                from pathlib import Path
                from app.utils.logging_setup import setup_logging

                result = setup_logging(logs_dir=Path({str(logs_dir)!r}))
                logging.getLogger("tests.restart").error({prior_message!r})
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", first_script],
                check=True,
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            self.assertEqual(completed.stderr, "")
            self.assertTrue((logs_dir / "error.log").is_file())

            second_script = textwrap.dedent(
                f"""
                from pathlib import Path
                from app.utils.logging_setup import setup_logging

                setup_logging(logs_dir=Path({str(logs_dir)!r}))
                """
            )
            subprocess.run(
                [sys.executable, "-c", second_script],
                check=True,
                capture_output=True,
                text=True,
                cwd=repo_root,
            )

            old_contents = (logs_dir / "error.old.log").read_text(encoding="utf-8")
            self.assertIn(prior_message, old_contents)
            self.assertEqual((logs_dir / "error.log").read_text(encoding="utf-8"), "")
```

- [x] **Step 2: Run test to verify it passes (or fails if rotation broken)**

```pwsh
python -m unittest tests.test_logging_setup.LogRestartRotationTests -v
```

Expected: PASS

- [x] **Step 3: Commit** *(satisfied-by-artifact: `LogRestartRotationTests` in `tests/test_logging_setup.py`; operator may defer git commit)*

```bash
git add tests/test_logging_setup.py
git commit -m "test: verify error.log rotation across process restart"
```

---

### Task 3: Gap Test — Worker Failure Redaction on Disk (OpenSpec 3.4)

**Files:**
- Modify: `tests/test_ui_main_window.py` (class `TestMainWindowWorkerLoggingIntegration`)

- [x] **Step 1: Write the failing worker redaction test**

Add to `TestMainWindowWorkerLoggingIntegration`:

```python
def test_worker_failed_redacts_api_key_in_log_file(self) -> None:
    tmp_dir = tempfile.mkdtemp()
    logs_dir = Path(tmp_dir)
    secret = "sk-test-redact-worker"
    try:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            config = AppConfig(
                api_key_storage_mode="local_plaintext",
                api_key=secret,
            )
            result = self._module._init_app_logging(config, logs_dir=logs_dir)
            self.assertIsNotNone(result)

            win = self._module.SpellScribeMainWindow(config=MagicMock())
            with patch("app.ui.main_window.QMessageBox.critical"):
                win._on_worker_failed(
                    "Detect Spells",
                    f"Authentication failed for key {secret}",
                )

            contents = _read_active_log_file(result)
            self.assertIn("[REDACTED]", contents)
            self.assertNotIn(secret, contents)
    finally:
        import shutil

        _release_main_window_test_logging(self._module, restore_setup=None)
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

**Note:** Clear `ANTHROPIC_API_KEY` so `_init_app_logging` redacts the `local_plaintext` config key, not a stray env var from the developer machine.

- [x] **Step 2: Run test**

```pwsh
python -m unittest tests.test_ui_main_window.TestMainWindowWorkerLoggingIntegration.test_worker_failed_redacts_api_key_in_log_file -v
```

Expected: PASS

- [x] **Step 3: Commit** *(satisfied-by-artifact: worker redaction test in `tests/test_ui_main_window.py` with `ANTHROPIC_API_KEY` isolation; operator may defer git commit)*

```bash
git add tests/test_ui_main_window.py
git commit -m "test: verify worker failure log redacts API key on disk"
```

---

### Task 4: Full Regression Run

**Files:**
- Test: entire suite

- [ ] **Step 1: Run full test suite**

```pwsh
python -m unittest discover tests/
```

Expected: `OK` (skipped count unchanged from baseline).

- [ ] **Step 2: Update verification report automated section**

In `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md`, set 3.1, 3.2, 3.4 to **PASS** with new test names; keep 3.3 and 3.5 as **PARTIAL (manual pending)**.

- [ ] **Step 3: Commit report update**

```bash
git add docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md
git commit -m "docs: update verification report after gap tests"
```

---

### Task 5: Manual Verification Checklist (OpenSpec 3.3 and 3.5)

**Environment:** Windows 10+, activated venv, no existing SpellScribe instances running.

**Logs directory:** `%APPDATA%\SpellScribe\logs`

- [ ] **Step 1: Prepare clean logs directory**

```pwsh
Remove-Item -Recurse -Force "$env:APPDATA\SpellScribe\logs" -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Manual 3.1 — Launch app and confirm log creation**

```pwsh
python -m app.ui.main_window
```

1. Leave app open.
2. In Settings → API storage `local_plaintext`, enter any test key, save.
3. Open a document and run **Detect Spells** with an invalid key or disconnected network to force `_on_worker_failed`.
4. Confirm `%APPDATA%\SpellScribe\logs\error.log` exists.
5. Open the file; confirm a line matches:

   `YYYY-MM-DD HH:MM:SS - <ThreadName> - app.ui.main_window - ERROR - ...`

   Thread name may be `MainThread` or a worker thread name depending on failure path.

6. Close the app.

Record in verification report: **3.1 manual: PASS/FAIL**

- [ ] **Step 3: Manual 3.2 — Restart rotation**

1. Note current `error.log` content from Step 2.
2. Relaunch: `python -m app.ui.main_window`, then close immediately.
3. Confirm prior content moved to `error.old.log`.
4. Confirm new `error.log` is empty or contains only new-session lines.

Record: **3.2 manual: PASS/FAIL**

- [ ] **Step 4: Manual 3.3 — Two concurrent instances**

1. Launch first instance: `python -m app.ui.main_window` (leave running).
2. Launch second instance in a **new terminal**: `python -m app.ui.main_window`.
3. Trigger a loggable error in **each** instance (e.g., Detect Spells failure).
4. Confirm:
   - `%APPDATA%\SpellScribe\logs\error.log` has first instance writes.
   - `%APPDATA%\SpellScribe\logs\error.1.log` exists with second instance writes.
   - Neither instance crashed on startup.
5. Close both instances.

Record: **3.3 manual: PASS/FAIL**

- [ ] **Step 5: Manual 3.4 — Redaction in real log file**

1. Set Settings → `local_plaintext` API key to a distinctive value (e.g., `sk-manual-redact-test`).
2. Force a worker failure whose message would include the key (invalid API call).
3. Open `error.log` (or `error.1.log` if second instance).
4. Confirm `[REDACTED]` appears and the raw key string does **not**.

Record: **3.4 manual: PASS/FAIL**

- [ ] **Step 6: Manual 3.5 — Open Logs Folder**

1. Launch app.
2. Click toolbar **Open Logs Folder**.
3. Confirm Windows Explorer opens `%APPDATA%\SpellScribe\logs`.
4. Confirm `error.log` is visible in that folder.

Record: **3.5 manual: PASS/FAIL**

- [ ] **Step 7: Update verification report manual section**

Add to `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md`:

```markdown
## Manual Checklist (YYYY-MM-DD)

| Task | Result | Notes |
|------|--------|-------|
| 3.1 | PASS | ... |
| 3.2 | PASS | ... |
| 3.3 | PASS | error.log + error.1.log |
| 3.4 | PASS | no raw key in file |
| 3.5 | PASS | Explorer opened logs dir |
```

- [ ] **Step 8: Commit manual results**

```bash
git add docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md
git commit -m "docs: record manual add-file-logging verification results"
```

---

### Task 6: OpenSpec Task Completion and Sign-Off

**Files:**
- Modify: `openspec/changes/add-file-logging/tasks.md`

- [ ] **Step 1: Mark tasks complete**

Update `openspec/changes/add-file-logging/tasks.md` — set `[x]` on items **1.1–3.5** only when the corresponding verification passed:

```markdown
## 1. Path and Utility Setup
- [x] 1.1 ...
- [x] 1.2 ...

## 2. Application Integration
- [x] 2.1 ...
- [x] 2.2 ...
- [x] 2.3 ...

## 3. Verification
- [x] 3.1 ...
- [x] 3.2 ...
- [x] 3.3 ...
- [x] 3.4 ...
- [x] 3.5 ...
```

- [ ] **Step 2: Add final assessment to verification report**

```markdown
## Final Assessment

All OpenSpec §3 verification tasks passed (automated + manual). Change is ready for archive review.
```

- [ ] **Step 3: Commit**

```bash
git add openspec/changes/add-file-logging/tasks.md docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md
git commit -m "docs(openspec): mark add-file-logging verification tasks complete"
```

---

## Out of Scope

- Archiving the OpenSpec change (`openspec archive add-file-logging`) — separate step after this plan.
- Frozen-build (`SpellScribe.exe`) verification — recommended smoke before release; not blocking dev sign-off.
- `extract_cli.py` file logging — explicitly deferred in design.
- In-app log viewer — non-goal per `design.md`.

---

## Grill-Me Self-Review (Pass 1)

| Branch | Question | Decision |
|--------|----------|----------|
| Prerequisite ordering | Verify §1–§2 before §3? | **Yes** — Task 0 gate prevents false PASS on missing implementation |
| 3.2 coverage | In-process tests enough? | **No** — add subprocess restart test (Task 2) |
| 3.3 coverage | Automate two GUIs? | **No** — manual only; simulated lock tests sufficient for CI |
| 3.4 worker path | Needed? | **Yes** — add one disk-write test (Task 3) |
| 3.5 Explorer | Mock enough for sign-off? | **No** — manual Explorer check required (Task 5) |
| Dev vs frozen | Which for manual? | **Dev** for §3 sign-off; frozen smoke noted as pre-release |
| tasks.md scope | Mark §1–§2 too? | **Yes**, when implementation verified — avoids stale all-`[ ]` state |
| Report artifact | Where? | **`docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md`** |

**Pass 1 confidence:** ~88% — manual steps need clearer failure trigger for Detect Spells.

---

## Grill-Me Self-Review (Pass 2 — refinements applied above)

| Branch | Resolution |
|--------|------------|
| How to force worker failure in manual steps | Settings `local_plaintext` + invalid key + **Detect Spells** on any open document; alternatively disconnect network |
| Empty `error.log` after rotation | Second process creates new empty file; assertion in Task 2 subprocess test uses `read_text() == ""` immediately after second `setup_logging` before new errors |
| Second instance rotation behavior | Manual 3.3 does **not** expect `error.old.log` for `error.1.log` — matches design trade-off |
| Non-Windows CI | Lock/claim/subprocess tests skip on non-win32; manual checklist is Windows-only by spec |
| Verification report in plans/ | Acceptable sibling to this plan; keeps sign-off evidence with other superpowers plans |

**Pass 2 confidence:** ~92% — subprocess test missing `cwd=repo_root` for `app` imports.

---

## Grill-Me Self-Review (Pass 3)

| Branch | Resolution |
|--------|------------|
| Subprocess import path | Added `cwd=Path(__file__).resolve().parents[1]` to both `subprocess.run` calls in Task 2 |
| Temp logs path in subprocess | Use `str(logs_dir)` in generated script literals so Windows paths embed correctly |
| Who runs manual checklist | Human operator before Task 6; agent can automate Tasks 0–4 only |
| Frozen EXE smoke | Documented out-of-scope for §3 sign-off; add to release checklist separately |

**Pass 3 confidence:** ~97% — ready for execution.

**Assumptions accepted:**
- Implementation from prior plans is already merged on branch `add-file-logging`.
- Manual verification is performed by a human on Windows before Task 6 checkbox commit.
- One skipped test in full suite (pre-existing) is acceptable if count unchanged.

**Open questions:** None blocking execution.
