## Context

The revised spec defines a Windows desktop workbench with three panels, toolbar commands, live progress, and session-aware file-open behavior. It also defines a settings dialog that persists app-level controls for models, OCR, confidence threshold, and credential storage mode.

This change depends on earlier data, ingestion, discovery, and review work. It does not include packaging.

## Goals / Non-Goals

**Goals:**
- Build the `QMainWindow` shell, splitter layout, and toolbar actions.
- Build the document panel and spell list panel around the session-state records.
- Wire worker signals, progress, cancel, and session restore prompts into the shell.
- Build the settings dialog and bind it to `AppConfig`.

**Non-Goals:**
- Implement packaging.
- Re-specify the extraction or export rules already covered by other changes.

## Decisions

### Let `SessionState` drive the whole shell
- The shell uses one source of truth for records, selection, and restore-by-hash behavior.
- Panels render from session state instead of keeping their own duplicate models.

Alternative considered:
- Keep panel-local state and sync it manually.
- Rejected because pending, review, and confirmed records already need shared ordering and selection behavior.

### Keep the shell responsible for file-open and file-switch prompts
- The main window already owns toolbar actions and can coordinate session restore and cancellation flows.
- This keeps prompt behavior in one place.
- The same ownership applies to the document-identity dialog and export dialog because both are toolbar-driven user flows.

Alternative considered:
- Push file-open decisions into the ingestion pipeline.
- Rejected because prompt text and user choice handling are UI concerns.

### Use one settings dialog bound to `AppConfig`
- A single dialog matches the revised spec and keeps persistence logic centralized.
- Keyring-backed credential mode stays a config choice while the secret itself stays outside the file.

Alternative considered:
- Split settings across multiple dialogs.
- Rejected because the current scope does not justify more UI surface.

## Risks / Trade-offs

- The shell touches many UI modules at once → Keep panel responsibilities narrow and use session state as the shared contract.
- Session restore and file-switch prompts can be easy to get wrong → Cover same-SHA reopen and different-SHA prompt behavior with tests.
- PDF rendering and highlight overlays can be heavy on large files → Keep rendering and highlight updates incremental.

## Migration Plan

- No migration is required.

## Open Questions

- None for this change.
