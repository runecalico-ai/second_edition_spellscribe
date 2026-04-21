## ADDED Requirements

### Requirement: The app provides a persistent settings dialog
The system SHALL provide a settings dialog that reads from and writes to `AppConfig`.

#### Scenario: Settings dialog loads saved values
- **WHEN** the user opens Settings
- **THEN** the dialog shows the current saved values from `AppConfig`

#### Scenario: Saving settings updates config
- **WHEN** the user saves changes in Settings
- **THEN** the app persists the updated file-based values to `config.json`

### Requirement: The settings dialog exposes extraction and OCR controls
The system SHALL let the user configure the revised-spec extraction and OCR settings.

#### Scenario: User can edit model and threshold settings
- **WHEN** the user opens Settings
- **THEN** the dialog includes controls for Stage 1 model, Stage 2 model, empty-page cutoff, max parallel extractions, OCR engine, and confidence threshold

#### Scenario: User can edit path defaults
- **WHEN** the user opens Settings
- **THEN** the dialog includes controls for default export directory, Tesseract path, and default source document name

### Requirement: The settings dialog exposes credential-source modes
The system SHALL let the user choose environment, credential-manager, or local-plaintext API-key storage mode.

#### Scenario: Credential-manager mode uses keyring metadata
- **WHEN** the user selects Remember on this PC
- **THEN** the app uses the keyring-backed credential-manager mode documented in the revised spec

### Requirement: The settings dialog can test API-key configuration
The system SHALL let the user test whether the current API-key configuration resolves successfully.

#### Scenario: Test action validates current key source
- **WHEN** the user activates the API-key test action in Settings
- **THEN** the app reports whether it can resolve a usable Anthropic API key from the current configuration
