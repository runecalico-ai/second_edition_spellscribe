## ADDED Requirements

### Requirement: The app provides a persistent settings dialog
The system SHALL provide a settings dialog that reads from and writes to `AppConfig`.

#### Scenario: Settings dialog loads saved values
- **WHEN** the user opens Settings
- **THEN** the dialog shows the current saved values from `AppConfig`

#### Scenario: Saving settings updates config
- **WHEN** the user clicks Save in the Settings dialog
- **THEN** the app persists the updated file-based values to `config.json`; changes take effect for the next user-initiated job, not for any currently running worker

#### Scenario: Cancelling settings discards changes
- **WHEN** the user closes the Settings dialog by clicking Cancel or pressing Escape
- **THEN** no changes are written to `config.json` and the in-memory `AppConfig` is unchanged

### Requirement: The settings dialog exposes extraction and OCR controls
The system SHALL let the user configure the revised-spec extraction and OCR settings.

#### Scenario: User can edit model and threshold settings
- **WHEN** the user opens Settings
- **THEN** the dialog includes controls for Stage 1 model, Stage 2 model, empty-page cutoff (`stage1_empty_page_cutoff`, non-negative integer), max concurrent extractions (`max_concurrent_extractions`, integer in range 1–20), OCR engine path, and confidence threshold (decimal 0.0–1.0)

#### Scenario: User can edit path defaults
- **WHEN** the user opens Settings
- **THEN** the dialog includes controls for default export directory, Tesseract executable path, and default source document name (`default_source_document`, used as the pre-filled value in the document-identity dialog)

#### Scenario: Advanced AppConfig fields are intentionally excluded from the dialog
- The following `AppConfig` fields are managed programmatically and are NOT surfaced in the settings dialog: `last_import_directory`, `last_export_scope`, `custom_schools`, `custom_spheres`, `document_names_by_sha256`, `document_offsets`, `force_ocr_by_sha256`, `stage2_max_attempts`, and `api_key` (the credential value itself, which is managed through the credential-source section below).

### Requirement: The settings dialog exposes credential-source modes
The system SHALL let the user choose environment, credential-manager, or local-plaintext API-key storage mode.

#### Scenario: Credential-manager mode uses keyring metadata
- **WHEN** the user selects Remember on this PC
- **THEN** the app uses the keyring-backed credential-manager mode (`credential_manager`) documented in the revised spec; the API key field in the dialog is hidden because the secret is stored in the OS keyring, not in `config.json`

#### Scenario: Environment-variable mode hides the key field
- **WHEN** the user selects Use environment variable
- **THEN** the app sets `api_key_storage_mode` to `env` and the API key text field is hidden; the dialog shows a note that the key must be set in the `ANTHROPIC_API_KEY` environment variable

#### Scenario: Local plaintext mode surfaces explicit risk
- **WHEN** the user selects Store in config file (insecure)
- **THEN** the dialog shows a clearly visible warning that the key will be stored unencrypted in `config.json` without OS keyring protection; the API key text field is shown as a password field with a show/hide toggle; the user must tick a confirmation checkbox before Save becomes enabled

#### Scenario: API key field masks the value
- **WHEN** the local-plaintext storage mode is active and the API key text field is visible
- **THEN** the field renders characters as password dots by default; a show/hide toggle button reveals or conceals the plaintext

### Requirement: The settings dialog can test API-key configuration
The system SHALL let the user test whether the current API-key configuration resolves successfully.

#### Scenario: Test action validates current key source
- **WHEN** the user activates the Test API Key button in Settings
- **THEN** the app attempts to resolve the Anthropic API key from the current (unsaved) credential-source selection and, if a non-empty key is found, makes a minimal Anthropic API call (e.g., a list-models or lightweight ping request) to verify connectivity; the result is shown inline in the dialog as a success or failure message with a brief error description on failure

#### Scenario: Test action is disabled when no key source is configured
- **WHEN** `env` mode is active and the `ANTHROPIC_API_KEY` environment variable is not set, or when `local_plaintext` mode is active and the key field is empty
- **THEN** the Test API Key button is disabled
