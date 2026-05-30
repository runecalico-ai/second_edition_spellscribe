# add-file-logging Verification Report

## Prerequisite Gate (2026-05-29)

**Tests:** `python -m unittest tests.test_logging_setup tests.test_paths tests.test_ui_main_window -v` — **OK** (195 ran, 1 skipped, 0 failures) on win32 (2026-05-29). Skipped: `test_cancel_mid_record_drops_only_inflight_record_deferred`.

**Symbols confirmed (read-only):**

| Symbol | File | Status |
|--------|------|--------|
| `spellscribe_logs_dir()` | `app/paths.py` | present |
| `setup_logging()`, `APIKeyRedactionFilter` | `app/utils/logging_setup.py` | present |
| `_init_app_logging()`, `_run_gui()`, `_on_open_logs_folder()` | `app/ui/main_window.py` | present |
| Toolbar action `"Open Logs Folder"` | `app/ui/main_window.py` | present |

## Automated Audit (2026-05-29)

### Execution

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

**Result:** 23/23 OK on win32 (2026-05-29).

| Task | Result | Primary tests |
|------|--------|---------------|
| 3.1 | PASS (automated); manual pending Task 5 | SetupLoggingTests.test_setup_logging_records_background_thread_name, TestMainWindowWorkerLoggingIntegration.test_worker_failed_writes_error_to_claimed_log |
| 3.2 | PASS | LogRotationTests (in-process), LogClaimTests.test_claim_log_file_path_rotates_primary_before_claiming, LogRestartRotationTests.test_setup_logging_rotates_primary_log_across_process_restart |
| 3.3 | PARTIAL | LogClaimTests (simulated lock), SetupLoggingTests.test_setup_logging_returns_result_that_keeps_claim_alive; manual pending Task 5 |
| 3.4 | PASS | APIKeyRedactionFilterTests, SetupLoggingTests.test_setup_logging_applies_redaction_filter, TestMainWindowWorkerLoggingIntegration.test_worker_failed_redacts_api_key_in_log_file |
| 3.5 | PARTIAL | TestMainWindowOpenLogsFolder (mocked); manual pending Task 5 |

**Note:** Task 1 Step 3 git commit intentionally deferred (operator did not request commit).
