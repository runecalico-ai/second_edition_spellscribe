## Why

Stage 1 discovery has its own prompt, state machine, and stop conditions. Splitting it into a separate change lets us validate pending-record creation and session restore behavior before we add Stage 2 extraction and human review.

## What Changes

- Add the Stage 1 boundary-detection prompt and response parsing.
- Prefix markdown lines with absolute line numbers before Stage 1 requests.
- Track active heading, end-of-spells-section, and empty-page cutoff state across pages.
- Create `Pending Extraction` records when a spell boundary becomes final.
- Persist pending records in session state and restore them on reopen.
- Define toolbar command semantics for `Detect Spells`.

## Capabilities

### New Capabilities
- `spell-discovery`: Stage 1 spell-boundary detection and pending-record management.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/pipeline/extraction.py`, `app/pipeline/detector.py`, `app/session.py`, `app/ui/main_window.py`, `app/ui/spell_list_panel.py`, `tests/**`
- Affected behavior: boundary detection, discovery stopping rules, pending queue creation, and session restore of pending records
- Dependencies: `anthropic`, `json`, session-state models from the core-model change
