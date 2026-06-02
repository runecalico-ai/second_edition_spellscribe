# Spec: file-logging

## Purpose

This capability covers persistent diagnostic log storage for SpellScribe, including session-scoped log rotation, multi-instance safety, API key redaction, and user access to log files.

## Requirements

### Requirement: Persistent Log Storage with Session Backup
The application SHALL maintain a persistent log file on the local filesystem and preserve one session of history.

#### Scenario: Log Rotation on Startup
- **WHEN** the application is launched
- **THEN** if `error.log` exists, it SHALL be renamed to `error.old.log` (overwriting any previous `error.old.log`).
- **AND** a new `error.log` SHALL be created.

### Requirement: Multi-Instance Safety
The system SHALL support multiple concurrent instances of the application without log-related crashes.

#### Scenario: Secondary Instance Logging
- **WHEN** the application is launched and `error.log` is locked by another process
- **THEN** the system SHALL attempt to use `error.1.log` (and subsequent numbers) until a writable file is found.

### Requirement: Log Content and Privacy
The application SHALL record detailed diagnostic information while protecting sensitive credentials.

#### Scenario: Detailed Metadata
- **WHEN** a log entry is written
- **THEN** it SHALL include: UTC timestamp, Thread Name, Logger Name, Log Level, and the Message.

#### Scenario: API Key Redaction
- **WHEN** a log message is about to be written to disk
- **AND** the message contains the configured API key
- **THEN** the API key SHALL be replaced with the string `[REDACTED]`.

### Requirement: User Accessibility
The application SHALL provide a convenient way for users to retrieve log files.

#### Scenario: Open Logs Folder
- **WHEN** the user selects "Open Logs Folder" from the main toolbar
- **THEN** the system SHALL open the `%APPDATA%\SpellScribe\logs` directory in the default file explorer.
