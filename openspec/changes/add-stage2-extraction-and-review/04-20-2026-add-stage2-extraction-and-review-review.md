## Summary
Total: 3 findings — 0 Critical, 1 High, 1 Medium, 1 Low

## Findings

### High
[H-001] (61) — Multiline `ALT[...]` candidates are truncated and corrupt `review_notes`
Plan ref: `openspec/changes/add-stage2-extraction-and-review/specs/spell-extraction-review/spec.md:73-75` (`Scenario: Merge conflict stores ALT candidate`)
Location: `app/utils/review_notes.py:5-47`, `app/pipeline/extraction.py:1062-1067`
Detail: Re-extract conflicts are written with `upsert_alt_tag()`, but `_format_alt_value()` passes scalar fields through `str(value)`. For multiline fields such as `description`, that writes literal newlines into `ALT[field]=...`. `_ALT_TAG_RE` stops at the first newline, so `parse_alt_tags()` truncates the candidate and `strip_alt_tags()` leaves the trailing lines behind in free-text notes. A local reproduction with `upsert_alt_tag('Manual note.', 'description', 'Line 1\nLine 2')` produced `{'description': 'Line 1'}` from `parse_alt_tags()` and `Manual note. Line 2` from `strip_alt_tags()`, so the required ALT candidate is not preserved correctly.

### Medium
[M-001] (44) — Confirmed duplicate conflicts are enforced only on save attempt, not as an inline blocking state
Plan ref: `openspec/changes/add-stage2-extraction-and-review/specs/spell-extraction-review/spec.md:65-67` (`Scenario: Confirmed save conflict blocks inline`)
Location: `app/pipeline/extraction.py:553-576`, `tests/test_pipeline_extraction.py:3126-3152`
Detail: `save_confirmed_changes()` detects the duplicate only when `Save Changes` is attempted, then raises `DuplicateConfirmedSpellError`. The reviewed implementation does not expose a preflight conflict helper or any other state the app could use to disable `Save Changes` before the click, so the spec's inline blocking behavior is only partially implemented.

### Low
[L-001] (19) — Normalized duplicate matching is not verified at the spec edge cases
Plan ref: `openspec/changes/add-stage2-extraction-and-review/specs/spell-extraction-review/spec.md:61-67` (`Scenario: Accept conflict offers overwrite, keep both, or skip`; `Scenario: Confirmed save conflict blocks inline`)
Location: `app/pipeline/extraction.py:1013-1034`, `tests/test_pipeline_extraction.py:3033-3152`
Detail: `_normalized_spell_identity()` lowercases names and collapses whitespace before duplicate comparison, which matches the plan's normalized-name rule. The tests only cover exact-string duplicates, though. There is no direct verification for inputs such as `Magic   Missile` versus ` magic missile `, so the normalization contract required by the plan remains untested.
