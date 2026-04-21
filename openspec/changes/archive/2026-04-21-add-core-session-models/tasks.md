## Sequencing

- Implement first.
- Later changes depend on these shared models, session persistence helpers, and config fields.

## 1. Core spell models

- [x] 1.1 Implement enums and canonical `Spell` and `LaxSpell` models in `app/models.py`
- [x] 1.2 Implement `TextRegion` and `CoordinateAwareTextMap` types with JSON-compatible serialization support

## 2. Session and config state

- [x] 2.1 Create `app/session.py` with `SpellRecordStatus`, `SpellRecord`, `SessionState`, and session load/save helpers
- [x] 2.2 Update `app/config.py` with persistent settings, keyring constants, and SHA-keyed document metadata fields

## 3. Validation tests

- [x] 3.1 Add unit tests for level normalization, school and sphere validation, and review-note flagging
- [x] 3.2 Add unit tests for `SessionState` and `AppConfig` serialization and load behavior
