## ADDED Requirements

### Requirement: The app provides a three-panel desktop workbench
The system SHALL provide a main desktop window with toolbar, status bar, and three coordinated panels.

#### Scenario: Main window shows core actions
- **WHEN** the app starts successfully
- **THEN** the main window shows actions for Open File, Detect Spells, Extract Selected, Extract All Pending, Export, and Settings

#### Scenario: Main window shows three coordinated panels
- **WHEN** the main window is open
- **THEN** it shows a document panel, a spell-list panel, and a right-side status or review panel

#### Scenario: Export action opens the export flow
- **WHEN** the user activates the Export action from the main window
- **THEN** the app opens the export dialog flow for JSON and Markdown output selection

### Requirement: The document panel renders the selected record context
The system SHALL render the source document and highlight the selected record.

#### Scenario: PDF selection highlights bounding boxes
- **WHEN** the selected record has PDF coordinate regions
- **THEN** the document panel highlights the union of those bounding boxes on the current PDF page

#### Scenario: DOCX selection highlights text offsets
- **WHEN** the selected record has DOCX character offsets
- **THEN** the document panel highlights the matching text range in the read-only text view

### Requirement: The spell list panel reflects record status
The system SHALL display records in confirmed, needs-review, and pending sections.

#### Scenario: Status sections stay separate
- **WHEN** the session contains records with different statuses
- **THEN** the spell list panel groups them into Confirmed, Needs Review, and Pending Extraction sections

#### Scenario: Selecting a pending record shows status view
- **WHEN** the user selects a pending record
- **THEN** the right panel shows the pending status view instead of the editable review form

#### Scenario: Selecting an extracted record shows editor view
- **WHEN** the user selects a confirmed or needs-review record
- **THEN** the right panel shows the review editor for that record

### Requirement: The review editor honors Stage 2 commit and duplicate rules
The workbench SHALL use Stage 2 pipeline APIs so commit actions and duplicate handling match `spell-extraction-review`.

#### Scenario: Confirmed save is blocked when duplicate preflight fires
- **WHEN** the selected record is `confirmed` and `get_confirmed_save_duplicate_conflict(session_state, spell_id=...)` returns a conflicting record for the current draft identity
- **THEN** the workbench keeps `Save Changes` disabled (or otherwise prevents commit) until the draft no longer collides on normalized name and class list

#### Scenario: Accept duplicate offers overwrite, keep both, or skip
- **WHEN** the user invokes Accept on a `needs_review` record whose draft conflicts with an existing confirmed record on normalized name and class list
- **THEN** the workbench offers overwrite, keep both, or skip, and passes the chosen `DuplicateResolutionStrategy` into `accept_review_record`

#### Scenario: Re-extract runs with focus prompt
- **WHEN** the user requests Re-extract with a focus prompt on a `needs_review` or `confirmed` record
- **THEN** the workbench calls `reextract_record_into_draft` with that prompt and updates the review editor from the merged draft

#### Scenario: Discard Draft clears the in-memory draft
- **WHEN** the user chooses Discard for a selected `needs_review` or `confirmed` record that has a draft
- **THEN** the workbench calls `discard_record_draft` on that record and refreshes the editor from `canonical_spell`

#### Scenario: Draft dirty state is visible
- **WHEN** the selected `needs_review` or `confirmed` record has `draft_dirty` set
- **THEN** the workbench shows a visible dirty state (for example a banner or indicator) until the user commits or discards

#### Scenario: Delete removes the record from the session
- **WHEN** the user confirms delete for a record shown in the spell list
- **THEN** the workbench calls `delete_record`, removes the row from the list, and clears selection if the deleted record was selected

### Requirement: The workbench manages progress, cancel, and session prompts
The system SHALL show extraction progress and SHALL handle restore and file-switch prompts according to the revised spec.

#### Scenario: Unknown document hash prompts for identity metadata
- **WHEN** the user opens a document whose SHA-256 has no stored metadata
- **THEN** the workbench shows the document-identity dialog before later pipeline stages continue

#### Scenario: Cancel preserves completed work
- **WHEN** the user cancels a running extraction
- **THEN** the app keeps completed pending and extracted records and drops only in-flight work

#### Scenario: Same-SHA reopen reuses active session
- **WHEN** the user opens a file whose SHA-256 matches the active session document
- **THEN** the app keeps the in-memory session and refreshes only the display path

#### Scenario: Different-SHA open prompts for unsaved work
- **WHEN** the user opens a file whose SHA-256 differs from the active session document
- **THEN** the app prompts to export, discard, or cancel before replacing the active session
