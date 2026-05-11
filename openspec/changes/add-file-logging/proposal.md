# Proposal: add-file-logging

## Problem
Frozen Windows applications (EXE) built with PyInstaller using `console=False` do not display `stderr` output. When critical operations like "Detect Spells" fail with a generic "Please try again" error message, users have no way to access the underlying technical error or stack trace, making troubleshooting and support nearly impossible.

## What Changes
We will implement a robust, file-based logging system that captures warnings and errors from the application.
- **Persistent Storage**: Logs will be saved to `%APPDATA%\SpellScribe\logs\error.log`.
- **Multi-Instance Support**: The system will detect if the primary log is in use and use numbered suffixes (e.g., `error.1.log`) for additional instances.
- **Session Lifecycle**: On startup, the previous `error.log` will be renamed to `error.old.log` to preserve history from the immediately preceding session, and a new empty log will be started.
- **Detailed Context**: Logs will include timestamps, thread names (for background workers), and logger names.
- **Sanitization**: Configured API keys will be automatically redacted from log messages.
- **User Accessibility**: An "Open Logs Folder" option will be added to the UI for easy log retrieval.

## Capabilities

### New Capabilities
- `file-logging`: Provides automated warning/error capture with session-based rotation and multi-instance safety.

### Modified Capabilities
- None

## Impact
- **app/paths.py**: Add support for resolving the `logs` subdirectory.
- **app/utils/logging_setup.py**: New module for logging configuration and API key redaction filter.
- **app/ui/main_window.py**: Initialize logging at startup and add a "Help > Open Logs Folder" action.
