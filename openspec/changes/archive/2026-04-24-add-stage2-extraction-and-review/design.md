## Context

The revised spec separates spell discovery from Stage 2 extraction and from the human review workflow. This change begins with pending records, runs Stage 2 only when the user asks for it, and ends with draft-backed review and explicit commit actions.

The design depends on the core session models, document ingestion, and discovery state. It does not include export or packaging.

## Goals / Non-Goals

**Goals:**
- Run Stage 2 only for selected or all pending records.
- Convert `LaxSpell` output into either canonical spell payloads or best-effort review placeholders.
- Update `SpellRecord` items in place as extraction completes.
- Implement draft-only editing for review and confirmed records.
- Implement duplicate handling, re-extract merge behavior, and commit-time learning of custom schools and spheres.

**Non-Goals:**
- Implement Stage 1 discovery.
- Implement export.
- Implement packaging.

### Presentation (deferred)
- Dirty-state banners, disabled actions, and duplicate-resolution **dialogs** belong in the **desktop workbench** (`add-desktop-shell-and-settings`). Stage 2 defines session invariants and pipeline APIs (`get_review_draft`, `apply_review_edits`, `get_confirmed_save_duplicate_conflict`, `accept_review_record`, etc.) that the shell must call; it does not ship Qt/widgets here.

## Decisions

### Update records in place instead of creating replacement records
- Stable `spell_id` values keep selection, ordering, and session restore simple.
- Record status changes from `pending_extraction` to `needs_review` or `confirmed` without replacing the record.

Alternative considered:
- Delete pending records and create new extracted records.
- Rejected because it makes selection, ordering, and autosave behavior harder to reason about.

### Keep draft edits separate from committed canonical data
- Review edits must not silently affect exports or later duplicate checks until the user commits.
- One autosaved draft per record supports crash recovery without implicit saves.

Alternative considered:
- Mutate the canonical spell on every field edit.
- Rejected because it blurs work-in-progress edits with committed state.

### Re-extract writes into the draft only
- Re-extract is advisory and can disagree with manual edits.
- Writing into the draft preserves the explicit commit model and makes conflicts visible.

Alternative considered:
- Auto-commit improved re-extract results.
- Rejected because later export would include model changes the user never accepted.

### Use the accept dialog only for review-to-confirm conflicts
- `Accept` can legitimately resolve an incoming review record against an existing confirmed record.
- `Save Changes` on an already-confirmed record should fail inline when it collides with another confirmed record.

Alternative considered:
- Reuse the overwrite dialog for confirmed edits.
- Rejected because the identity and replacement semantics become confusing once both records already exist in Confirmed.

## Risks / Trade-offs

- Stage 2 can still produce malformed output after retries → Always create a best-effort review record instead of dropping data.
- Draft and canonical state can diverge for long periods → The workbench SHALL make commit points and dirty-state warnings explicit (see Presentation deferred above).
- Re-extract merge rules can be hard to verify → Keep the merge field-aware and test conflicts through focused unit tests.

## Migration Plan

- No migration is required beyond using the existing `SpellRecord` and `SessionState` structures.

## Open Questions

- None for this change.
