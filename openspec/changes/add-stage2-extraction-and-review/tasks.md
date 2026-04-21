## Sequencing

- Implement after `add-core-session-models`, `add-document-ingestion-and-identity`, and `add-discovery-and-pending-queue`.
- Finish this before `add-export-capabilities` and `add-desktop-shell-and-settings` so record status transitions, drafts, and merge rules are already defined.

## 1. Stage 2 extraction pipeline

- [ ] 1.1 Implement selected and all-pending Stage 2 queueing with in-place `SpellRecord` updates
- [ ] 1.2 Implement `LaxSpell` conversion, retry handling, and placeholder review fallback behavior
- [ ] 1.3 Add the CLI extraction harness for single-file test runs

## 2. Review and confirmation flow

- [ ] 2.1 Implement the draft-backed review form for `needs_review` and `confirmed` records
- [ ] 2.2 Implement `Accept`, `Save Changes`, `Discard Draft`, `Delete`, and duplicate-resolution behavior
- [ ] 2.3 Implement `Re-extract` focus prompts and draft-only field-aware merge behavior
- [ ] 2.4 Implement `parse_alt_tags`, `upsert_alt_tag`, and `strip_alt_tags` helpers and integrate them into re-extract flows

## 3. Verification

- [ ] 3.1 Add tests for Stage 2 post-routing, placeholder fallback, and in-place status transitions
- [ ] 3.2 Add tests for draft commit rules, duplicate handling, and re-extract merge behavior
