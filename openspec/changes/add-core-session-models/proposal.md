## Why

The revised spec depends on a stable state model before any ingestion, extraction, or UI work can behave correctly. We need the canonical spell schema, the session envelope, and the config contract first so later changes can build on stable types instead of ad hoc state.

## What Changes

- Add the canonical spell content models for `Spell`, `LaxSpell`, `TextRegion`, and `CoordinateAwareTextMap`.
- Add session-level models for `SpellRecord`, `SpellRecordStatus`, and `SessionState`.
- Define file-based persistence rules for `session.json` and `config.json`, including SHA-256 document identity and autosave metadata.
- Define the app config contract for OCR overrides, document offsets, custom schools and spheres, and API-key storage mode.
- Add tests for schema validation, level normalization, school and sphere validation, and session and config serialization.

## Capabilities

### New Capabilities
- `core-session-models`: Canonical spell schemas, session-state records, and config persistence for the desktop app.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/models.py`, `app/session.py`, `app/config.py`, `tests/**`
- Affected behavior: spell validation, session persistence, config persistence, and document identity storage
- Dependencies: `pydantic`, `keyring`, standard-library JSON and file I/O
