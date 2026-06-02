# Design: add-file-logging

## Context
The SpellScribe application is a desktop tool that uses Python's standard `logging` module to record technical errors. In the current implementation, these logs are only directed to standard error (`stderr`). While this works during development, it is insufficient for end-users running the frozen Windows application (`.exe`), where `stderr` is not captured or displayed.

## Goals / Non-Goals

**Goals:**
- Provide a persistent log file on disk for troubleshooting frozen builds.
- Preserves exactly one session of history (`error.old.log`) to assist with crash investigation after a restart.
- Handle multiple running instances without file-locking crashes.
- Ensure sensitive data (API keys) are not leaked into the log files.
- Make logs easily accessible to non-technical users via the UI.

**Non-Goals:**
- Implementing a full log viewer within the application UI.
- Long-term log archival (more than one previous session).

## Decisions

### 1. Multi-Instance Logic
To prevent sharing violations on Windows, the logging setup will attempt to open `error.log`. If it fails (file locked), it will increment a counter and try `error.1.log`, `error.2.log`, etc. This ensures that every concurrent session gets its own log file.

### 2. Session Lifecycle (The "One-Backup" Strategy)
On startup, before initializing the logger, the code will check for an existing `error.log`. If found, it will attempt to rename it to `error.old.log`. This provides a safety net for "restart after crash" scenarios.

### 3. Log Formatting and Level
- **Level**: `WARNING` and above.
- **Format**: `%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s`.
- The `asctime` will use UTC to avoid ambiguity across time zones.

### 4. API Key Redaction
We will implement a `logging.Filter` that checks log messages against the `AppConfig.api_key`. Since the key is not available at the exact moment of startup, the filter will be initialized with an empty key and updated immediately after `AppConfig.load()` or when the user updates settings.

### 5. UI Entry Point
Since the application currently uses a Toolbar-centric UI, a new "Open Logs" action will be added to the main **Toolbar**. This will use `os.startfile(logs_dir)` to open the directory in Windows Explorer.

## Risks / Trade-offs

- **Risk: Multiple Instances and Backups**: If multiple instances are run, only the primary `error.log` has an `error.old.log` backup. Secondary logs (`error.1.log`) are simply truncated. This is a trade-off for implementation simplicity.
- **Trade-off: Toolbar Space**: Adding a button to the toolbar uses valuable horizontal space, but it ensures the feature is discoverable without introducing a MenuBar system.
