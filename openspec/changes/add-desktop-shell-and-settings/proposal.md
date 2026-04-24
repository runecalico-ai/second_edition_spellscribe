## Why

The application still needs a usable desktop workbench even after the data and pipeline pieces exist. Splitting the shell and settings work into its own change keeps UI composition, session prompts, and config editing reviewable without mixing them with export or packaging.

## What Changes

- Add the three-panel main window shell with toolbar, progress bar, and status bar.
- Add the document panel for PDF and DOCX display with record highlighting.
- Add the three-section spell list panel for confirmed, review, and pending records.
- Add the right-side review and pending-status panel host so the shell can switch between editor and status views.
- Add the document-identity dialog and export dialog flows for toolbar-driven actions.
- Add worker progress, cancel, and same-SHA restore/file-switch prompt behavior.
- Add the settings dialog with model, OCR, threshold, export-path, credential-source controls, API-key test action, and other fields required by `settings-management` (including empty-page cutoff, `max_concurrent_extractions`, default source document name, and related controls spelled out in that delta spec).
- Wire the review editor to Stage 2 APIs: `get_review_draft`, `apply_review_edits`, duplicate preflight (`get_confirmed_save_duplicate_conflict`) to disable Save, Accept duplicate resolution (`DuplicateResolutionStrategy`), `draft_dirty` and Discard, Re-extract entry points, and `delete_record` where the product exposes delete.

## Capabilities

### New Capabilities
- `desktop-workbench`: Main application window, panel layout, record navigation, and session-aware file-open flow.
- `settings-management`: Persistent desktop settings for extraction, OCR, export, and credential-source behavior.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/ui/main_window.py`, `app/ui/document_panel.py`, `app/ui/spell_list_panel.py`, `app/ui/review_panel.py`, `app/ui/settings_dialog.py`, `app/session.py`, `app/config.py`, `tests/**`
- Affected behavior: file-open flow, record navigation, progress and cancel UI, settings persistence, and session restore prompts
- Dependencies: `PySide6` (add to `requirements.txt` when this change is implemented), session-state models, config persistence, extraction worker signals
