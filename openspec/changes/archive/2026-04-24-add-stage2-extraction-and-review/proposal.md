## Why

After discovery creates pending records, SpellScribe still needs a controlled way to extract structured spell data, route weak results to review, and let users commit or discard edits safely. This change adds the Stage 2 extraction path and the review workflow without mixing those rules into discovery or export.

## What Changes

This change delivers **pipeline and session APIs** for Stage 2 and review; **buttons, dialogs, and panels** are implemented under `add-desktop-shell-and-settings`.

- Add Stage 2 extraction commands for selected pending records and for all pending records.
- Convert `LaxSpell` output into canonical `Spell` payloads or best-effort placeholder review records.
- Update `SpellRecord` items in place as extraction completes.
- Add the draft-backed review **data path** for `Needs Review` and `Confirmed` records (workbench form defers to desktop change).
- Add service-layer `Accept`, `Save Changes`, `Discard Draft`, `Delete`, and `Re-extract` behavior (workbench invokes these).
- Add duplicate handling, re-extract merge rules, and custom school and sphere learning on committed edits.
- Add the `review_notes` helper functions that manage `ALT[...]` metadata during merge (and for callers that parse notes).
- Add the CLI extraction harness from the revised spec.

## Capabilities

### New Capabilities
- `spell-extraction-review`: Stage 2 extraction, record routing, draft editing, and confirmation flow for discovered spells.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/pipeline/extraction.py` (Stage 2, review, commit, delete, re-extract APIs), `app/models.py`, `app/session.py` (models only; no new UI), `app/utils/review_notes.py`, `extract_cli.py`, `tests/**`
- **UI panels** (review editor, spell list, toolbars): `add-desktop-shell-and-settings` (not part of this change)
- Affected behavior: Stage 2 command flow, review routing, duplicate resolution, re-extract merge, and draft commit rules
- Dependencies: `anthropic`, `pydantic`, review-note helpers, session-state models (see `requirements.txt`; structured output uses Pydantic validation, not the `instructor` package in this repo)
