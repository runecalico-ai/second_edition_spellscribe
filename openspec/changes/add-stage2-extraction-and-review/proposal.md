## Why

After discovery creates pending records, SpellScribe still needs a controlled way to extract structured spell data, route weak results to review, and let users commit or discard edits safely. This change adds the Stage 2 extraction path and the review workflow without mixing those rules into discovery or export.

## What Changes

- Add Stage 2 extraction commands for selected pending records and for all pending records.
- Convert `LaxSpell` output into canonical `Spell` payloads or best-effort placeholder review records.
- Update `SpellRecord` items in place as extraction completes.
- Add the draft-backed review flow for `Needs Review` and `Confirmed` records.
- Add `Accept`, `Save Changes`, `Discard Draft`, `Delete`, and `Re-extract` behavior.
- Add duplicate handling, re-extract merge rules, and custom school and sphere learning on committed edits.
- Add the `review_notes` helper functions that manage `ALT[...]` metadata during merge and export cleanup.
- Add the CLI extraction harness from the revised spec.

## Capabilities

### New Capabilities
- `spell-extraction-review`: Stage 2 extraction, record routing, draft editing, and confirmation flow for discovered spells.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/pipeline/extraction.py`, `app/ui/review_panel.py`, `app/ui/spell_list_panel.py`, `app/session.py`, `app/utils/review_notes.py`, `extract_cli.py`, `tests/**`
- Affected behavior: Stage 2 command flow, review routing, duplicate resolution, re-extract merge, and draft commit rules
- Dependencies: `anthropic`, `instructor`, `pydantic`, review-note helpers, session-state models
