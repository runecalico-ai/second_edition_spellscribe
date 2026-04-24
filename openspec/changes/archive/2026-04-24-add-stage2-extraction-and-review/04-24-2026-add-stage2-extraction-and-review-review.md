# Code Review: add-stage2-extraction-and-review

**Date:** 2026-04-24
**Review passes:** 3 independent (completeness, accuracy, edge cases)
**Source of truth:** `openspec/changes/add-stage2-extraction-and-review/`
**Reviewed files:** `app/pipeline/extraction.py`, `app/utils/review_notes.py`, `extract_cli.py`,
`tests/test_pipeline_extraction.py`, `tests/test_review_notes.py`

---

## Summary

Total: 12 findings — 0 Critical, 1 High, 6 Medium, 5 Low

All spec requirements are implemented. All implementation logic is correct.
The sole High finding is a behavioral inconsistency in provenance enforcement between the two
commit paths. All remaining findings are test coverage gaps; the underlying code is correct.

---

## Findings

### High

#### [H-001] (65) — `save_confirmed_changes` skips provenance enforcement; `accept_review_record` does not

Plan ref: Design doc "Must call `_enforce_authoritative_provenance` before committing" (established for
`accept_review_record` and verified by `test_accept_review_duplicate_overwrite_preserves_review_provenance_consistency`)

Location: `app/pipeline/extraction.py` — `save_confirmed_changes()` vs `accept_review_record()`

Detail: `accept_review_record` calls `_enforce_authoritative_provenance` before committing the draft,
overwriting `source_document`, `source_page`, `extraction_start_line`, and `extraction_end_line` with
values derived from the record's boundary lines — so user-supplied or model-supplied provenance edits
cannot persist. `save_confirmed_changes` commits the raw `candidate` draft without this call. A user who
edits provenance fields in a confirmed record's draft and calls `save_confirmed_changes` will successfully
persist those values in `canonical_spell`, producing confirmed spells whose provenance disagrees with the
record boundaries they were extracted from. This will affect export accuracy. No test exists for
`save_confirmed_changes` that verifies provenance is re-anchored to record boundaries.

```python
# accept_review_record — provenance enforced (correct)
authoritative_candidate = _enforce_authoritative_provenance(session_state, record=record, spell=candidate)
_commit_spell_to_record(record, authoritative_candidate, status=SpellRecordStatus.CONFIRMED)

# save_confirmed_changes — provenance NOT enforced (inconsistency)
candidate = get_review_draft(record)
_commit_spell_to_record(record, candidate, status=SpellRecordStatus.CONFIRMED)
```

---

### Medium

#### [M-001] (45) — No test for `reextract_record_into_draft` raising `RuntimeError` when all retries fail

Plan ref: spec.md "Scenario: Re-extract merges into draft only" (failure path); tasks.md 2.3

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`; implementation in
`reextract_record_into_draft()` in `app/pipeline/extraction.py`

Detail: Unlike `_extract_pending_record`, which falls back to a placeholder spell on exhausted retries,
`reextract_record_into_draft` raises `RuntimeError("Stage 2 re-extract failed") from last_error` when
`candidate_spell` remains `None`. No test verifies that this raises (rather than degrading silently),
and no test confirms the original `last_error` is chained as the cause.

---

#### [M-002] (40) — No tests for status-guard errors in `accept_review_record` and `save_confirmed_changes`

Plan ref: spec.md "Requirement: Commit actions follow status-specific rules"

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`

Detail: `accept_review_record` raises `InvalidRecordStateError` for any status other than `NEEDS_REVIEW`
(i.e. CONFIRMED or PENDING_EXTRACTION callers). `save_confirmed_changes` raises for any status other than
`CONFIRMED`. Four guard paths have no test. `test_reextract_rejects_pending_records` covers the reextract
guard, but the equivalent accept/save guards are untested.

---

#### [M-003] (38) — No isolated tests for merge branches where candidate matches draft or canonical

Plan ref: spec.md "Scenario: Re-extract merges into draft only" — three-way merge rule

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests.test_reextract_merges_into_draft_and_records_alt_conflict_candidates`;
implementation in `_merge_reextract_candidate()` in `app/pipeline/extraction.py`

Detail: `_merge_reextract_candidate` has three branches: (a) draft == canonical → accept candidate;
(b) candidate == draft OR candidate == canonical → keep draft, no ALT tag; (c) three-way conflict →
keep draft, write ALT tag. Only branch (c) is directly exercised. Branches (a) and (b) are incidentally
covered by the same test but not isolated, so a regression in either would not be caught by a
dedicated assertion.

---

#### [M-004] (35) — No test for `apply_review_edits` rejecting invalid data without mutating state

Plan ref: spec.md "Scenario: Editing does not change committed spell immediately"

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`; `apply_review_edits()` in
`app/pipeline/extraction.py`

Detail: `apply_review_edits` validates via `Spell.model_validate` before assigning `record.draft_spell`.
If validation raises, `draft_spell` and `draft_dirty` are not modified. No test passes invalid field
values (e.g. `level="not-an-int"`) and asserts that the record state is unchanged, so this atomicity
invariant is untested.

---

#### [M-005] (32) — No test for `get_review_draft` raising `InvalidRecordStateError` when neither draft nor canonical exists

Plan ref: spec.md "Scenario: Review draft is read from draft or canonical"

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`; `get_review_draft()` in
`app/pipeline/extraction.py`

Detail: `get_review_draft` raises `InvalidRecordStateError` when both `draft_spell` and `canonical_spell`
are `None`. This can occur on a `NEEDS_REVIEW` record constructed without a canonical spell. The error
path exists in code but has no test.

---

#### [M-006] (30) — No test for `reextract_record_into_draft` raising `InvalidRecordStateError` when `canonical_spell` is None

Plan ref: spec.md "Scenario: Re-extract merges into draft only" (requires canonical for merge comparison)

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`; `reextract_record_into_draft()`
in `app/pipeline/extraction.py`

Detail: `reextract_record_into_draft` raises `InvalidRecordStateError("record has no canonical spell to
compare against")` when `canonical_spell is None`. A `NEEDS_REVIEW` record without a canonical spell
(e.g. constructed programmatically) would hit this guard. No test covers it.

---

### Low

#### [L-001] (20) — No tests for `extract_selected_pending` no-op paths

Plan ref: spec.md "Scenario: Extract Selected uses selected pending records only"

Location: `tests/test_pipeline_extraction.py` — `Stage2ExtractionTests`

Detail: Three no-op return paths lack dedicated tests: (a) `selected_spell_id` is `None`; (b) the
selected record exists but its status is not `PENDING_EXTRACTION`; (c) `selected_spell_id` does not
match any record. All three are correctly implemented but untested.

---

#### [L-002] (18) — No test for `delete_record` on a `CONFIRMED` record

Plan ref: spec.md "Scenario: Delete removes record and clears selection when needed"

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`

Detail: `test_delete_record_removes_selected_record` uses a `NEEDS_REVIEW` record. `delete_record` is
status-agnostic, but the spec scenario does not restrict deletion to any status and no test confirms
it works on a `CONFIRMED` record.

---

#### [L-003] (15) — No test for `upsert_alt_tag` raising `ValueError` on blank field name

Plan ref: tasks.md 2.4 "Implement `parse_alt_tags`, `upsert_alt_tag`, and `strip_alt_tags`"

Location: `tests/test_review_notes.py`; `upsert_alt_tag()` in `app/utils/review_notes.py`

Detail: `upsert_alt_tag` raises `ValueError("field must not be blank")` for empty or whitespace-only
field names. This contract exists in code but no test exercises it.

---

#### [L-004] (12) — No test for `accept_review_record` with `config=None` confirming no crash and no learning

Plan ref: spec.md "Scenario: Save and Accept pass config for term learning"

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`

Detail: `save_confirmed_changes` has a test that passes `config=None` implicitly (no config kwarg),
confirming no crash. No equivalent test exists for `accept_review_record`. Both functions guard
with `if config is not None:`, but only save has a passing test at `config=None`.

---

#### [L-005] (10) — Minor isolated coverage gaps: merge `review_notes` exclusion, blank custom terms, self-exclude in duplicate detection

Plan ref: tasks.md 2.4 (merge integration); spec.md duplicate detection; spec.md custom term learning

Location: `tests/test_pipeline_extraction.py` — `ReviewFlowServiceTests`; `_merge_reextract_candidate()`,
`_find_confirmed_duplicate()`, `_merge_custom_terms()` in `app/pipeline/extraction.py`

Detail: Three low-risk behaviors have no dedicated test: (a) `_merge_reextract_candidate` explicitly
skips the `review_notes` field — verified only incidentally; (b) `_merge_custom_terms` silently drops
blank/whitespace-only terms — the filter exists but no test passes blank strings as input;
(c) `_find_confirmed_duplicate` excludes the record being committed via `excluding_spell_id` —
relied upon throughout but no test isolates this self-exclusion logic.
