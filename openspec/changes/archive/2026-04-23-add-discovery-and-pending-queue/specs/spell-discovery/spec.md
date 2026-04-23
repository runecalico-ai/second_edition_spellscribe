## ADDED Requirements

### Requirement: Stage 1 requests use numbered markdown lines
The system SHALL prefix page markdown with absolute line numbers before it sends a Stage 1 discovery request.

#### Scenario: Numbered page text is sent to the model
- **WHEN** the app sends a page to Stage 1 discovery
- **THEN** each markdown line includes its absolute zero-based line number

### Requirement: Discovery tracks heading and stop state across pages
The system SHALL maintain sequential discovery state across the document.

#### Scenario: Active heading carries forward
- **WHEN** Stage 1 returns a non-null `active_heading`
- **THEN** the worker uses that heading for later spell spans until a new heading replaces it

#### Scenario: End-of-spells-section stops discovery
- **WHEN** Stage 1 returns `end_of_spells_section=true`
- **THEN** the worker closes any current pending span and stops discovery for the file

#### Scenario: Empty-page cutoff stops discovery after spells start
- **WHEN** the worker reaches the configured empty-page cutoff after at least one spell has already been found
- **THEN** the worker stops discovery for the file

### Requirement: Discovery creates pending extraction records
The system SHALL create `Pending Extraction` records when a spell span becomes final.

#### Scenario: Next spell start closes previous span
- **WHEN** the worker finds a new spell start after an existing open span
- **THEN** the system closes the previous span and stores it as a pending record

#### Scenario: End of file closes final span
- **WHEN** the worker reaches the last page with an open spell span
- **THEN** the system closes that span and stores it as a pending record

### Requirement: Pending records persist in session state
The system SHALL autosave and restore pending discovery records.

#### Scenario: Cancel preserves pending records
- **WHEN** discovery is canceled after pending spans have been closed
- **THEN** the session save includes those pending records

#### Scenario: Reopen restores pending records by hash
- **WHEN** the user reopens the same source file and the stored session hash matches
- **THEN** the app restores the pending records without rerunning Stage 1

### Requirement: Detect Spells runs Stage 1 only
The system SHALL keep discovery separate from Stage 2 extraction commands.

#### Scenario: Detect Spells does not start extraction
- **WHEN** the user runs `Detect Spells`
- **THEN** the app creates pending records and does not start Stage 2 extraction automatically
