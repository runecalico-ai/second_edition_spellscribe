## ADDED Requirements

### Requirement: Stage 2 runs only on pending records
The system SHALL run Stage 2 extraction only for selected `Pending Extraction` records or for all current pending records.

#### Scenario: Extract Selected uses selected pending records only
- **WHEN** `extract_selected_pending` is invoked and `SessionState.selected_spell_id` identifies a `Pending Extraction` record
- **THEN** the pipeline queues only that record for Stage 2

#### Scenario: Extract All Pending uses all pending records
- **WHEN** `extract_all_pending` is invoked
- **THEN** the pipeline queues every current `Pending Extraction` record for Stage 2

### Requirement: Stage 2 updates records in place
The system SHALL update the existing `SpellRecord` as Stage 2 completes.

#### Scenario: Weak extraction becomes review record
- **WHEN** extracted output is below the confidence threshold or marks itself for review
- **THEN** the existing record changes to `needs_review`

#### Scenario: Clean extraction becomes confirmed record
- **WHEN** extracted output meets the confidence threshold and does not require review
- **THEN** the existing record changes to `confirmed`

### Requirement: Failed extraction still creates editable review data
The system SHALL create a best-effort review record when Stage 2 cannot produce a clean canonical spell.

#### Scenario: Validation failure creates placeholder review record
- **WHEN** Stage 2 exhausts retries without producing a committable validated `Spell` (including failures while coercing the model payload, calling `LaxSpell.to_spell`, or enforcing provenance)
- **THEN** the system stores a best-effort placeholder spell derived from excerpt and record metadata, fills missing fields with defaults, and marks the record for review

#### Scenario: Unparseable response keeps the record editable
- **WHEN** Stage 2 fails after all retries because the response is unparseable
- **THEN** the system stores a placeholder spell with review notes instead of dropping the record

### Requirement: Review edits stay in draft state until commit
The system SHALL keep review and confirmed edits in `draft_spell` until the user commits them.

**Normative usage:** `apply_review_edits`, `discard_record_draft`, and the commit helpers are defined for `needs_review` and `confirmed` records. The workbench and other callers MUST restrict invocations to those statuses; behavior for `pending_extraction` or other states is out of scope for this capability.

#### Scenario: Editing does not change committed spell immediately
- **WHEN** field updates are applied through the review draft API (`apply_review_edits`) for a `needs_review` or `confirmed` record
- **THEN** the system updates `draft_spell` and leaves `canonical_spell` unchanged

#### Scenario: Review draft is read from draft or canonical
- **WHEN** a caller needs the editable spell for a `needs_review` or `confirmed` record
- **THEN** `get_review_draft` returns `draft_spell` when present, otherwise a deep copy of `canonical_spell` suitable for editing into a new draft

#### Scenario: Discard Draft restores committed spell
- **WHEN** `discard_record_draft` is invoked for a record that has a draft
- **THEN** the system clears `draft_spell` so the committed `canonical_spell` is the effective spell again

### Requirement: Commit actions follow status-specific rules
The system SHALL use different commit actions for review and confirmed records.

#### Scenario: Accept moves review record to confirmed
- **WHEN** `accept_review_record` is invoked for a `needs_review` record whose draft passes validation and no duplicate conflict applies (or duplicate resolution commits)
- **THEN** the system commits the draft to `canonical_spell` and changes the record status to `confirmed`

#### Scenario: Accept duplicate skip leaves record uncommitted
- **WHEN** `accept_review_record` is invoked with default `duplicate_resolution` (`SKIP`) and a confirmed duplicate exists for the draft identity
- **THEN** the call returns `False`, the record stays `needs_review`, and nothing is committed

#### Scenario: Save Changes updates confirmed record
- **WHEN** `save_confirmed_changes` is invoked for a `confirmed` record whose draft passes validation and no confirmed duplicate applies
- **THEN** the system commits the draft to `canonical_spell` and keeps the record status as `confirmed`

### Requirement: Duplicate and re-extract handling preserve user control
The system SHALL apply duplicate resolution and re-extract merge rules from the revised spec.

#### Scenario: Accept conflict supports overwrite, keep both, or skip
- **WHEN** a review draft conflicts with an existing confirmed record on normalized name and class list
- **THEN** `accept_review_record` supports overwrite, keep both, or skip via `DuplicateResolutionStrategy`

#### Scenario: Confirmed save duplicate is detectable before commit
- **WHEN** a confirmed record's draft conflicts with another confirmed record on normalized name and class list
- **THEN** `get_confirmed_save_duplicate_conflict` returns the conflicting record, and `save_confirmed_changes` raises `DuplicateConfirmedSpellError` until the draft no longer collides

#### Scenario: Re-extract merges into draft only
- **WHEN** `reextract_record_into_draft` is invoked with a focus area
- **THEN** the system merges returned values into the draft only and preserves unrelated user edits

#### Scenario: Merge conflict stores ALT candidate
- **WHEN** for a field the draft differs from canonical (a manual edit) and the re-extract candidate is neither equal to the draft nor equal to canonical
- **THEN** the system keeps the draft field value and stores the candidate in `review_notes` as a single `ALT[field_name]` tag for later review

### Requirement: Record deletion removes the spell from the session
The system SHALL support removing a spell record from the active session without corrupting selection state.

#### Scenario: Delete removes record and clears selection when needed
- **WHEN** `delete_record(session_state, spell_id=...)` is invoked with a `spell_id` that exists in `SessionState.records`
- **THEN** the call returns `True`, that record is removed from the session list, and if it was the selected record, selection is cleared

#### Scenario: Delete is a no-op for unknown spell id
- **WHEN** `delete_record` is invoked with a `spell_id` that is not in `SessionState.records`
- **THEN** the call returns `False` and the session list is unchanged

### Requirement: Custom terms learning on commit
The system SHALL learn custom schools and spheres from spells when committing review or confirmed drafts with `AppConfig` supplied.

#### Scenario: Save and Accept pass config for term learning
- **WHEN** `save_confirmed_changes` or `accept_review_record` commits a spell and a non-None `config` is provided
- **THEN** the system updates `AppConfig` custom school and sphere lists from the committed spell where applicable
