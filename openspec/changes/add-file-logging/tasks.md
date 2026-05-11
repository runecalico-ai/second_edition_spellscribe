# Tasks: add-file-logging

## 1. Path and Utility Setup

- [ ] 1.1 Update `app/paths.py` to resolve the `logs` subdirectory.
- [ ] 1.2 Implement `app/utils/logging_setup.py` with:
    - [ ] `APIKeyRedactionFilter` for log sanitization.
    - [ ] `setup_logging()` with multi-instance lock detection and `error.old.log` rotation.

## 2. Application Integration

- [ ] 2.1 Initialize logging in the `main_window.py` entry point.
- [ ] 2.2 Add "Help > Open Logs Folder" menu action to `SpellScribeMainWindow`.
- [ ] 2.3 Pass the current API key from `AppConfig` to the logging filter whenever the config is loaded or updated.

## 3. Verification

- [ ] 3.1 Verify log creation and detailed format (including thread name).
- [ ] 3.2 Verify `error.old.log` rotation on restart.
- [ ] 3.3 Verify multi-instance safe logging (open two apps, check for `error.1.log`).
- [ ] 3.4 Verify API key redaction in the log file.
- [ ] 3.5 Verify "Open Logs Folder" menu action opens Explorer.
