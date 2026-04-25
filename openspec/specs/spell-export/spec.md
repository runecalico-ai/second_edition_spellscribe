# Spell Export

## Purpose
The Spell Export capability provides shared export filtering, ordering, and rendering logic for producing JSON and Markdown export files from committed canonical spell data. It enforces consistent scope rules, atomic file writes, and clean human-facing output across both formats.

## Requirements

### Requirement: Export uses committed canonical spells only
The system SHALL export committed canonical `Spell` objects only.

#### Scenario: Pending records are excluded
- **WHEN** the user exports any scope
- **THEN** `Pending Extraction` records do not appear in the export output

#### Scenario: Dirty drafts are not exported
- **WHEN** a record has a dirty draft
- **THEN** export still uses the committed canonical spell data

#### Scenario: export.py functions are pure data functions
- **WHEN** `to_json()` or `to_markdown()` is called
- **THEN** they accept a pre-filtered `list[Spell]` and write to a path; they do not access `SessionState` or perform dirty-draft detection; all session inspection and the dirty-draft warning dialog are the responsibility of the calling UI layer

### Requirement: Export scope uses shared ordering rules
The system SHALL apply the same scope and ordering rules to JSON and Markdown export. The export scope is represented by an `ExportScope` enum with values `CONFIRMED_ONLY`, `NEEDS_REVIEW_ONLY`, and `EVERYTHING_EXTRACTED` (not `ALL`, to avoid implying pending records are included).

#### Scenario: Confirmed-only export uses persisted confirmed order
- **WHEN** the user exports the Confirmed-only scope
- **THEN** the output order matches the persisted Confirmed-section order and ignores temporary audit sort state

#### Scenario: Needs-review-only export uses persisted needs-review order
- **WHEN** the user exports the Needs-review-only scope
- **THEN** the output order matches the persisted Needs Review-section `section_order`, top to bottom, ignoring any temporary sort state

#### Scenario: Everything-extracted uses merged line order
- **WHEN** the user exports the Everything-extracted scope (`ExportScope.EVERYTHING_EXTRACTED`)
- **THEN** the output includes only confirmed and needs-review records and sorts them by `extraction_start_line` ascending; spells with a missing or `-1` `extraction_start_line` sort after all well-keyed spells; ties on `extraction_start_line` break by `name` case-insensitive ascending

### Requirement: JSON export uses version 1.1 envelope rules
The system SHALL write JSON export files in the documented version 1.1 envelope format.

#### Scenario: JSON export includes provenance fields
- **WHEN** the app writes a JSON export file
- **THEN** the output includes `version`, `exported_at`, `spellscribe_version`, and `spells`; `spellscribe_version` is the semver string from `app.__version__` (e.g. `"1.0.0"`); `exported_at` is a UTC timestamp formatted as `YYYY-MM-DDTHH:MM:SSZ` (e.g. `"2026-04-19T12:34:56Z"`), produced via `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`

#### Scenario: JSON export omits internal-only fields
- **WHEN** the app writes spell objects to JSON
- **THEN** the output omits `confidence`, `extraction_start_line`, and `extraction_end_line`

#### Scenario: JSON normalizes empty review_notes to null
- **WHEN** `strip_alt_tags(review_notes)` returns an empty or whitespace-only string
- **THEN** the JSON spell object writes `"review_notes": null` rather than an empty string

#### Scenario: Wizard JSON omits sphere
- **WHEN** the app exports a Wizard spell to JSON
- **THEN** the spell object omits the `sphere` key

### Requirement: Markdown export mirrors JSON filtering and cleanup rules
The system SHALL render Markdown export with the same scope, ordering, and clean-export filters as JSON export.

#### Scenario: Markdown strips internal ALT tags
- **WHEN** the app renders review notes into Markdown
- **THEN** the value passed to the Jinja2 template is the result of calling `strip_alt_tags(review_notes)`, producing human-facing text with all inline `ALT[...]` tags removed

#### Scenario: Markdown shows review section when needed
- **WHEN** a spell needs review or has review notes
- **THEN** the Markdown output includes the Review subsection for that spell

#### Scenario: Markdown renders Cantrip and Quest level labels
- **WHEN** the app renders a Wizard spell with level 0 or a Priest spell with level 8
- **THEN** the Markdown level field displays `Cantrip` (Wizard level 0) or `Quest` (Priest level 8) rather than the raw integer

#### Scenario: Clean export can still include review notes
- **WHEN** `clean_only` is true and a spell has `needs_review == false` but non-empty `review_notes`
- **THEN** the spell is included in the export and the Markdown Review subsection renders the human-facing `review_notes` text (the Review subsection only triggers on `needs_review or review_notes`, not on `needs_review` alone)

### Requirement: Clean export checkbox is disabled for Needs-review-only scope
The system SHALL disable the Clean export checkbox when the scope is Needs-review-only, because every record in that scope has `needs_review == true` and enabling it would always produce an empty file.

#### Scenario: Clean export checkbox is greyed out for Needs-review-only scope
- **WHEN** the user selects the Needs-review-only export scope
- **THEN** the Clean export checkbox is disabled and unchecked in the export dialog

### Requirement: Last-used export scope is persisted across sessions
The system SHALL remember the last-used export scope between sessions via `AppConfig.last_export_scope` (default: `"everything_extracted"`).

#### Scenario: Export dialog opens with last-used scope
- **WHEN** the export dialog opens
- **THEN** the scope selector is pre-set to the value stored in `AppConfig.last_export_scope`

#### Scenario: Chosen scope is saved on successful export
- **WHEN** the user completes a successful export
- **THEN** `AppConfig.last_export_scope` is updated to the scope that was used

### Requirement: Export warns when dirty drafts exist
The system SHALL warn users before export when dirty drafts are present.

#### Scenario: Dirty-draft warning appears before export
- **WHEN** at least one record has a dirty draft and the user starts export
- **THEN** the app shows a blocking modal dialog naming the count of dirty-draft records and warning that uncommitted edits will not be included, with buttons "Continue Export" and "Cancel"; choosing "Cancel" aborts the export and returns the user to the session

### Requirement: Export dialog resolves output paths and persists the chosen directory
The system SHALL propose a default output path, enforce file extensions, and update `AppConfig.export_directory` after a successful export.

#### Scenario: Both paths are collected before any file is written
- **WHEN** the user selects both JSON and Markdown formats
- **THEN** the dialog collects both output paths upfront before writing either file, so cancelling the second path prompt does not leave a partial JSON file on disk

#### Scenario: Default filename is proposed from source document name
- **WHEN** the export dialog opens
- **THEN** the default filename for each format is `<AppConfig.default_source_document>.<ext>` rooted in `AppConfig.export_directory`, where `<ext>` is `json` or `md` (spaces in the document name are replaced with underscores to produce a safe filename)

#### Scenario: Empty export result produces a warning
- **WHEN** the filtered spell list is empty after applying scope and clean-only filters
- **THEN** the app shows a non-blocking warning before writing the file, informing the user that no spells match the current export settings; the export proceeds and writes an envelope with an empty `spells` array (JSON) or an empty file (Markdown)

#### Scenario: File extension is enforced by the save dialog filter
- **WHEN** the user saves a JSON export file
- **THEN** the file dialog filter restricts the extension to `.json`; when saving Markdown the filter restricts to `.md`; overwrite confirmation is handled by the native `QFileDialog` and no additional app-level prompt is required

#### Scenario: Successful export updates the default export directory
- **WHEN** the user completes a successful export
- **THEN** the directory portion of the chosen path is written back to `AppConfig.export_directory`

### Requirement: Export files are written atomically
The system SHALL write export files using an atomic temp-file-then-replace pattern.

#### Scenario: Atomic write leaves no temp files on success
- **WHEN** an export write completes successfully
- **THEN** no `.tmp` sibling files remain on disk and the output file contains correct content

#### Scenario: Atomic write does not corrupt existing file on failure
- **WHEN** an export write fails after the temp file is created but before the rename
- **THEN** the original output file (if any) is not corrupted or truncated
