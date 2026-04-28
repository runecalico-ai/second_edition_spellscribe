## Why

The application still needs a usable desktop workbench even after the data and pipeline pieces exist. Splitting the shell and settings work into its own change keeps UI composition, session prompts, and config editing reviewable without mixing them with export or packaging.

## What Changes

- Add the three-panel main window shell with toolbar, progress bar, and status bar; include empty-state placeholders and toolbar enable/disable rules tied to worker and session state.
- Add the document panel: PDF rendering via PyMuPDF → `QPixmap` in a `QScrollArea` with bounding-box highlight overlays; DOCX rendering in a read-only `QTextEdit` with character-range highlights via `setExtraSelections`.
- Add the three-section spell list panel for confirmed, needs-review, and pending records.
- Add the right-side review and pending-status panel host so the shell can switch between the review editor and the pending status view (name, extraction order, line range).
- Add the document-identity dialog (shown for new document hashes; aborting cancels the open operation) and the export dialog launch (delegates to the export module from `add-export-capabilities`).
- Add `QThread`-based worker classes for Detect Spells and Extract jobs with typed signals (`record_extracted`, `progress_updated`, `extraction_cancelled`, `extraction_failed`) and cancel via a shared `threading.Event`.
- Add the settings dialog with model, OCR, threshold, export-path, credential-source controls, API-key test action, and the other fields required by `settings-management`; Cancel discards changes; changes apply on the next user-initiated job, not to any running worker.
- Wire the review editor to Stage 2 APIs: `get_review_draft`, `apply_review_edits`, duplicate preflight (`get_confirmed_save_duplicate_conflict`) to disable Save, Accept duplicate resolution (`DuplicateResolutionStrategy`) via a modal dialog, `discard_record_draft`, Re-extract (`reextract_record_into_draft`) via a focus-prompt input dialog, and `delete_record`.

## Capabilities

### New Capabilities
- `desktop-workbench`: Main application window, panel layout, record navigation, worker threading model, and session-aware file-open flow.
- `settings-management`: Persistent desktop settings for extraction, OCR, export, and credential-source behavior.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/ui/main_window.py`, `app/ui/document_panel.py`, `app/ui/spell_list_panel.py`, `app/ui/review_panel.py`, `app/ui/settings_dialog.py`, `app/ui/workers.py`, `app/session.py`, `app/config.py`, `tests/**`
- Affected behavior: file-open flow, record navigation, progress and cancel UI, settings persistence, and session restore prompts
- Dependencies: `PySide6` (add to `requirements.txt` when this change is implemented), `pymupdf` (already a dependency), session-state models, config persistence, extraction worker signals, export dialog from `add-export-capabilities`
