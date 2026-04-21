# Capability: core-session-models

## Purpose
Define the canonical spell, session, and config contracts that later ingestion, extraction, review, and export workflows depend on.

## Requirements

### Requirement: Canonical spell schema
The system SHALL define a canonical spell-content schema that represents extracted AD&D 2nd Edition spells for validation, review, and export.

#### Scenario: Wizard spell validates with canonical fields
- **WHEN** a Wizard spell includes required identity, stat block, description, and source fields
- **THEN** the system validates it as a canonical `Spell`

#### Scenario: Priest spell requires sphere values
- **WHEN** a Priest spell omits the `sphere` field or provides an empty sphere list
- **THEN** the system rejects the canonical `Spell`

### Requirement: Level normalization and range validation
The system SHALL normalize spell levels and enforce class-specific level ranges.

#### Scenario: Cantrip normalizes to zero
- **WHEN** extraction supplies `level="Cantrip"` for a Wizard spell
- **THEN** the system stores the canonical level as `0`

#### Scenario: Quest normalizes to eight
- **WHEN** extraction supplies `level="Quest"` for a Priest spell
- **THEN** the system stores the canonical level as `8`

#### Scenario: Invalid Priest level is rejected
- **WHEN** a Priest spell has a canonical level outside `1..8`
- **THEN** the system rejects the canonical `Spell`

### Requirement: Unknown schools and spheres flag review
The system SHALL allow freeform schools and spheres while marking unknown values for review.

#### Scenario: Unknown school sets review state
- **WHEN** a spell contains a school value outside the canonical set and outside the configured custom list
- **THEN** the system marks the spell as needing review

#### Scenario: Unknown sphere appends review notes
- **WHEN** a Priest spell contains a sphere value outside the canonical and custom sets
- **THEN** the system appends a note that identifies the unknown sphere

### Requirement: Session state stores workflow records
The system SHALL store document workflow state in a versioned `SessionState` envelope.

#### Scenario: Session envelope stores document identity
- **WHEN** the app saves session state
- **THEN** the session includes `source_sha256_hex` and `last_open_path`

#### Scenario: Session envelope stores record list
- **WHEN** the app saves session state
- **THEN** the session includes ordered `SpellRecord` items and the full `CoordinateAwareTextMap`

### Requirement: Spell records track canonical and draft state separately
The system SHALL keep committed spell data separate from draft spell edits.

#### Scenario: Record stores committed spell data
- **WHEN** a record has completed extraction
- **THEN** the system can store its committed spell in `canonical_spell`

#### Scenario: Record stores draft edits independently
- **WHEN** the user edits a record in the review UI
- **THEN** the system stores the in-progress form state in `draft_spell` without changing `canonical_spell`

### Requirement: Config persistence separates file settings from remembered credentials
The system SHALL store file-based app settings in `config.json` and SHALL keep credential-manager secrets outside that file.

#### Scenario: File-based settings save to config
- **WHEN** the app saves configuration
- **THEN** it writes export paths, OCR overrides, document offsets, and schema extensions to `config.json`

#### Scenario: Credential-manager mode uses fixed key names
- **WHEN** the app stores the Anthropic API key in credential-manager mode
- **THEN** it uses service name `SpellScribe` and account name `anthropic_api_key`
