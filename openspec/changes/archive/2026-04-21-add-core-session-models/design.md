## Context

The revised SpellScribe spec depends on strong core types before any document ingestion, extraction pipeline, or UI work can be stable. The application needs one canonical spell schema, one session envelope keyed by document SHA-256, and one config contract for app data, schema extensions, and credential storage.

The repo does not have any existing implementation code. This change creates the data contracts that later changes will consume. Those later changes include document routing, spell discovery, Stage 2 extraction, review editing, export, and desktop UI composition.

Constraints:
- Python 3.12 is required.
- The canonical spell payload must stay compatible with the revised spec.
- Session persistence must support autosave and restore without requiring re-ingestion.
- Config persistence must remain file-based, while credential-manager secrets stay outside `config.json`.

## Goals / Non-Goals

**Goals:**
- Define the canonical `Spell` and `LaxSpell` models.
- Define `TextRegion` and `CoordinateAwareTextMap` for source mapping.
- Define `SpellRecord`, `SpellRecordStatus`, and `SessionState` for in-memory and persisted app state.
- Define the `AppConfig` contract for file paths, OCR overrides, document offsets, schema extensions, and API-key storage mode.
- Make the models serializable and testable.

**Non-Goals:**
- Implement document ingestion.
- Implement Stage 1 or Stage 2 LLM calls.
- Implement UI widgets or window layout.
- Implement JSON or Markdown export.
- Implement packaging.

## Decisions

### Use `Spell` as the canonical exported payload and wrap it in `SpellRecord`
- `Spell` stays focused on extracted spell content, validation, and export fields.
- `SpellRecord` owns workflow state such as pending discovery, section order, draft state, and boundary metadata.
- This split prevents UI-only state from leaking into exported payloads.

Alternative considered:
- Store all workflow fields on `Spell`.
- Rejected because pending records and draft-only edits do not always have a valid canonical spell payload.

### Store one versioned `SessionState` per active document
- `SessionState` groups document identity, coordinate mapping, record list, and current selection.
- A version field keeps the format forward-compatible for later migrations.
- SHA-256 remains the document identity key.

Alternative considered:
- Store separate JSON files for records, coordinate maps, and UI state.
- Rejected because autosave and atomic replace are simpler with one envelope.

### Keep config and secret storage separate
- `config.json` stores file-based app settings only.
- Credential-manager mode stores the Anthropic API key through `keyring` under a fixed service and account name.
- Plaintext config storage remains an advanced fallback only.

Alternative considered:
- Store all modes in `config.json`.
- Rejected because the revised spec explicitly prefers Windows Credential Manager for remembered secrets.

### Make manual `source_page` overrides explicit on the record
- `manual_source_page_override` tracks whether a spell page was edited by the user.
- Later document-offset changes can update derived page numbers without overwriting manual corrections.

Alternative considered:
- Infer overrides by diffing current values against calculated values.
- Rejected because that is brittle and makes later migration logic harder.

## Risks / Trade-offs

- Model sprawl across `Spell`, `SpellRecord`, `SessionState`, and `AppConfig` → Keep boundaries strict and document field ownership in code comments and tests.
- Early decisions can constrain later UI or pipeline work → Keep workflow fields generic enough to support pending, review, and confirmed states.
- Session format changes can break restore for older files → Keep `version` on `SessionState` and tolerate unknown config keys.
- Credential-manager behavior can vary across Windows setups → Keep `env` mode as the simplest fallback and allow plaintext storage only as an advanced option.

## Migration Plan

- This is a greenfield change with no shipped app state to migrate.
- Include versioned session and config structures from the start.
- Preserve the documented legacy-offset migration hook in `AppConfig` for future compatibility.

## Open Questions

- None for this change. The revised spec already fixes the model and persistence boundaries.
