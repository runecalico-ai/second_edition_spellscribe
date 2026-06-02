# Tasks: add-file-logging

## 1. Path and Utility Setup

- [x] 1.1 Update `app/paths.py` to resolve the `logs` subdirectory.
- [x] 1.2 Implement `app/utils/logging_setup.py` with:
    - [x] `APIKeyRedactionFilter` for log sanitization.
    - [x] `setup_logging()` with multi-instance lock detection and `error.old.log` rotation.

## 2. Application Integration

- [x] 2.1 Initialize logging in the `main_window.py` entry point.
- [x] 2.2 Add "Open Logs Folder" toolbar action to `SpellScribeMainWindow`.
- [x] 2.3 Pass the current API key from `AppConfig` to the logging filter whenever the config is loaded or updated.

## 3. Verification

- [ ] 3.1 Verify log creation and detailed format (including thread name). H-001: automated/proxy evidence exists, but required Task 5 manual GUI/log-inspection checklist is not yet truthfully completed.
- [ ] 3.2 Verify `error.old.log` rotation on restart. H-001: automated/proxy evidence exists, but required Task 5 manual restart/log-inspection checklist is not yet truthfully completed.
- [x] 3.3 Verify multi-instance safe logging (open two apps, check for `error.1.log`).
- [ ] 3.4 Verify API key redaction in the log file. H-001: automated/proxy evidence exists, but required Task 5 manual Settings/plaintext-key failure flow and log inspection are not yet truthfully completed.
- [x] 3.5 Verify "Open Logs Folder" toolbar action opens Explorer.
