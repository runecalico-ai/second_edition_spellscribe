## Sequencing

- Implement after `add-core-session-models` and `add-document-ingestion-and-identity`.
- Finish this before `add-stage2-extraction-and-review` and `add-desktop-shell-and-settings` so pending records and discovery state already exist.

## 1. Stage 1 request and response handling

- [x] 1.1 Implement numbered-page prompt generation and JSON response parsing for discovery
- [x] 1.2 Implement `active_heading`, `end_of_spells_section`, and empty-page cutoff state handling

## 2. Pending-record lifecycle

- [x] 2.1 Implement span-closing logic that creates `pending_extraction` records only when boundaries are final
- [x] 2.2 Persist pending records through session autosave and restore-by-hash flows

## 3. Verification

- [x] 3.1 Add unit tests for heading carry-forward, end-of-section stop, and empty-page cutoff behavior
- [x] 3.2 Add tests for cross-page span closure and pending-record persistence
