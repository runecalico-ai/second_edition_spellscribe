## ADDED Requirements

### Requirement: Stage 2 runs only on pending records
The system SHALL run Stage 2 extraction only for selected `Pending Extraction` records or for all current pending records.

#### Scenario: Extract Selected uses selected pending records only
- **WHEN** the user runs `Extract Selected`
- **THEN** the app queues only the selected `Pending Extraction` records for Stage 2

#### Scenario: Extract All Pending uses all pending records
- **WHEN** the user runs `Extract All Pending`
- **THEN** the app queues all current `Pending Extraction` records for Stage 2

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
- **WHEN** `LaxSpell.to_spell()` fails strict validation
- **THEN** the system stores parseable fields, fills missing fields with defaults, and marks the record for review

#### Scenario: Unparseable response keeps the record editable
- **WHEN** Stage 2 fails after all retries because the response is unparseable
- **THEN** the system stores a placeholder spell with review notes instead of dropping the record

### Requirement: Review edits stay in draft state until commit
The system SHALL keep review and confirmed edits in `draft_spell` until the user commits them.

#### Scenario: Editing does not change committed spell immediately
- **WHEN** the user edits a review or confirmed record in the form
- **THEN** the app updates `draft_spell` and leaves `canonical_spell` unchanged

#### Scenario: Discard Draft restores committed spell
- **WHEN** the user chooses `Discard Draft`
- **THEN** the app removes the draft and reloads the committed canonical spell

### Requirement: Commit actions follow status-specific rules
The system SHALL use different commit actions for review and confirmed records.

#### Scenario: Accept moves review record to confirmed
- **WHEN** a review record passes validation and the user clicks `Accept & Move to Confirmed`
- **THEN** the app commits the draft to `canonical_spell` and changes the record status to `confirmed`

#### Scenario: Save Changes updates confirmed record
- **WHEN** a confirmed record passes validation and the user clicks `Save Changes`
- **THEN** the app commits the draft to `canonical_spell` and keeps the record status as `confirmed`

### Requirement: Duplicate and re-extract handling preserve user control
The system SHALL apply duplicate resolution and re-extract merge rules from the revised spec.

#### Scenario: Accept conflict offers overwrite, keep both, or skip
- **WHEN** a review record conflicts with an existing confirmed record on normalized name and class list
- **THEN** the app offers overwrite, keep both, or skip behavior

#### Scenario: Confirmed save conflict blocks inline
- **WHEN** a confirmed draft conflicts with another confirmed record on normalized name and class list
- **THEN** the app disables `Save Changes` until the conflict is resolved

#### Scenario: Re-extract merges into draft only
- **WHEN** the user re-extracts a record with a focus area
- **THEN** the app merges the returned values into the draft only and preserves unrelated user edits

#### Scenario: Merge conflict stores ALT candidate
- **WHEN** re-extract returns a value that conflicts with a manual edit and improvement is not provable
- **THEN** the app keeps the manual value and stores one `ALT[field_name]` candidate in `review_notes`
