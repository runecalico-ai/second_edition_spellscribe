# Desktop Workbench

## Purpose
The Desktop Workbench capability defines the main three-panel SpellScribe desktop UI, including document context rendering, record review workflows, background job controls, and session-aware document-open behavior.

## Requirements

### Requirement: The app provides a three-panel desktop workbench
The system SHALL provide a main desktop window with toolbar, status bar, and three coordinated panels.

#### Scenario: Main window shows core actions
- **WHEN** the app starts successfully
- **THEN** the main window shows actions for Open File, Detect Spells, Extract Selected, Extract All Pending, Export, and Settings

#### Scenario: Main window shows three coordinated panels
- **WHEN** the main window is open
- **THEN** it shows a document panel, a spell-list panel, and a right-side status or review panel

#### Scenario: Toolbar shows empty-state placeholder before any document is opened
- **WHEN** the app starts and no session is loaded
- **THEN** the document panel, spell list panel, and right panel each show a placeholder message, and the toolbar actions Detect Spells, Extract Selected, Extract All Pending, and Export are disabled

#### Scenario: Window title reflects the open document
- **WHEN** a document is open
- **THEN** the window title shows the document file name followed by "— SpellScribe"

#### Scenario: Export action opens the export flow
- **WHEN** the user activates the Export action from the main window
- **THEN** the app opens the export dialog flow for JSON and Markdown output selection

#### Scenario: Toolbar extraction actions are disabled while a worker is active
- **WHEN** a Detect Spells or Extract worker is running
- **THEN** the Detect Spells, Extract Selected, and Extract All Pending toolbar actions are disabled until the worker finishes or is cancelled

#### Scenario: Detect Spells completion refreshes the spell list
- **WHEN** the Detect Spells worker completes successfully
- **THEN** the status bar shows a summary of pending records found and the spell list panel refreshes to show them

#### Scenario: Extract All Pending completion updates the spell list
- **WHEN** the Extract All Pending worker finishes (normally or after cancel)
- **THEN** the spell list panel reflects the updated record statuses and the status bar shows how many records were extracted

### Requirement: The document panel renders the selected record context
The system SHALL render the source document and highlight the selected record.

#### Scenario: PDF selection highlights bounding boxes
- **WHEN** the selected record has PDF coordinate regions
- **THEN** the document panel renders the relevant PDF page via PyMuPDF and paints highlight overlays for the union of those bounding boxes, scrolling to bring the highlighted region into view

#### Scenario: DOCX selection highlights text offsets
- **WHEN** the selected record has DOCX character offsets
- **THEN** the document panel displays the extracted Markdown text in a read-only `QTextEdit` and highlights the matching character range using `setExtraSelections`

### Requirement: The spell list panel reflects record status
The system SHALL display records in confirmed, needs-review, and pending sections.

#### Scenario: Status sections stay separate
- **WHEN** the session contains records with different statuses
- **THEN** the spell list panel groups them into Confirmed, Needs Review, and Pending Extraction sections

#### Scenario: Selecting a pending record shows status view
- **WHEN** the user selects a pending record
- **THEN** the right panel shows the pending status view, which displays the spell name (if known from Stage 1), the extraction order, and the source line range from `boundary_start_line`/`boundary_end_line`

#### Scenario: Selecting an extracted record shows editor view
- **WHEN** the user selects a confirmed or needs-review record
- **THEN** the right panel shows the review editor for that record, seeded from `get_review_draft`

### Requirement: The review editor honors Stage 2 commit and duplicate rules
The workbench SHALL use Stage 2 pipeline APIs so commit actions and duplicate handling match `spell-extraction-review`.

#### Scenario: Editor seeds from draft on selection
- **WHEN** the user selects a confirmed or needs-review record
- **THEN** the review editor is populated by calling `get_review_draft` on that record; subsequent field edits are applied via `apply_review_edits` on focus-out or explicit Apply

#### Scenario: Confirmed save is blocked when duplicate preflight fires
- **WHEN** the selected record is `confirmed` and `get_confirmed_save_duplicate_conflict(session_state, spell_id=...)` returns a conflicting record for the current draft identity
- **THEN** the workbench keeps `Save Changes` disabled (or otherwise prevents commit) until the draft no longer collides on normalized name and class list

#### Scenario: Accept duplicate offers overwrite, keep both, or skip
- **WHEN** the user invokes Accept on a `needs_review` record whose draft conflicts with an existing confirmed record on normalized name and class list
- **THEN** the workbench offers overwrite, keep both, or skip via a modal dialog, and passes the chosen `DuplicateResolutionStrategy` into `accept_review_record`; choosing Skip leaves the record in `needs_review` and closes the dialog without committing

#### Scenario: Re-extract prompts for a focus prompt then runs
- **WHEN** the user activates the Re-extract action on a `needs_review` or `confirmed` record
- **THEN** the workbench shows a text-input dialog (via `QInputDialog.getText`) to collect the focus prompt string; on confirm it calls `reextract_record_into_draft` with that string and refreshes the editor from the returned merged draft; on cancel it does nothing

#### Scenario: Discard Draft clears the in-memory draft
- **WHEN** the user chooses Discard for a selected `needs_review` or `confirmed` record that has a draft
- **THEN** the workbench calls `discard_record_draft` on that record and refreshes the editor from `canonical_spell`

#### Scenario: Draft dirty state is visible
- **WHEN** the selected `needs_review` or `confirmed` record has `draft_dirty` set
- **THEN** the workbench shows a visible dirty-state indicator (for example a banner or asterisk in the panel title) until the user commits or discards

#### Scenario: Delete removes the record from the session
- **WHEN** the user confirms delete for a record shown in the spell list
- **THEN** the workbench calls `delete_record`, removes the row from the list, and clears selection if the deleted record was selected

### Requirement: The workbench manages progress, cancel, and session prompts
The system SHALL show extraction progress and SHALL handle restore and file-switch prompts according to the revised spec.

#### Scenario: Unknown document hash prompts for identity metadata
- **WHEN** the user opens a document whose SHA-256 has no stored metadata
- **THEN** the workbench shows the document-identity dialog before any later pipeline stage continues; if the user cancels that dialog, the open operation is aborted and the current session (if any) remains unchanged

#### Scenario: Cancel button stops the running worker
- **WHEN** a Detect Spells or Extract worker is running
- **THEN** the toolbar shows a Cancel action (or the progress area includes a Cancel button) that, when activated, signals the worker to stop after completing any in-flight record

#### Scenario: Cancel preserves completed work
- **WHEN** the user cancels a running extraction
- **THEN** the app keeps all already-completed pending and extracted records and drops only the in-flight record

#### Scenario: Same-SHA reopen reuses active session
- **WHEN** the user opens a file whose SHA-256 matches the active session document
- **THEN** the app keeps the in-memory session and refreshes only the display path shown in the title bar and status bar

#### Scenario: Different-SHA open prompts for unsaved work
- **WHEN** the user opens a file whose SHA-256 differs from the active session document and the session has confirmed or needs-review records
- **THEN** the app prompts with three choices: Export (opens the export dialog then replaces the session), Discard (replaces the session immediately), or Cancel (aborts the open operation)
