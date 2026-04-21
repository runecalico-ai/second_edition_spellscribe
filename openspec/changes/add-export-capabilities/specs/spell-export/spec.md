## ADDED Requirements

### Requirement: Export uses committed canonical spells only
The system SHALL export committed canonical `Spell` objects only.

#### Scenario: Pending records are excluded
- **WHEN** the user exports any scope
- **THEN** `Pending Extraction` records do not appear in the export output

#### Scenario: Dirty drafts are not exported
- **WHEN** a record has a dirty draft
- **THEN** export still uses the committed canonical spell data

### Requirement: Export scope uses shared ordering rules
The system SHALL apply the same scope and ordering rules to JSON and Markdown export.

#### Scenario: Confirmed-only export uses persisted confirmed order
- **WHEN** the user exports the Confirmed-only scope
- **THEN** the output order matches the persisted Confirmed-section order and ignores temporary audit sort state

#### Scenario: Everything-extracted uses merged line order
- **WHEN** the user exports the Everything-extracted scope
- **THEN** the output includes only confirmed and needs-review records and sorts them by `extraction_start_line` with the documented fallback tie-break rule

### Requirement: JSON export uses version 1.1 envelope rules
The system SHALL write JSON export files in the documented version 1.1 envelope format.

#### Scenario: JSON export includes provenance fields
- **WHEN** the app writes a JSON export file
- **THEN** the output includes `version`, `exported_at`, `spellscribe_version`, and `spells`

#### Scenario: JSON export omits internal-only fields
- **WHEN** the app writes spell objects to JSON
- **THEN** the output omits `confidence`, `extraction_start_line`, and `extraction_end_line`

#### Scenario: Wizard JSON omits sphere
- **WHEN** the app exports a Wizard spell to JSON
- **THEN** the spell object omits the `sphere` key

### Requirement: Markdown export mirrors JSON filtering and cleanup rules
The system SHALL render Markdown export with the same scope, ordering, and clean-export filters as JSON export.

#### Scenario: Markdown strips internal ALT tags
- **WHEN** the app renders review notes into Markdown
- **THEN** the output omits internal `ALT[...]` lines

#### Scenario: Markdown shows review section when needed
- **WHEN** a spell needs review or has review notes
- **THEN** the Markdown output includes the Review subsection for that spell

### Requirement: Export warns when dirty drafts exist
The system SHALL warn users before export when dirty drafts are present.

#### Scenario: Dirty-draft warning appears before export
- **WHEN** at least one record has a dirty draft and the user starts export
- **THEN** the app warns that uncommitted edits will not be included unless they are saved first
