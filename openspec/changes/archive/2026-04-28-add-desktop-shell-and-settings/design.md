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

### Use `QThread` with a `QObject`-based worker for background extraction
- Each Detect Spells or Extract job runs on a dedicated `QThread`; the shell spawns up to `max_concurrent_extractions` concurrent threads via a coordinator/manager object.
- Workers emit typed Qt signals (`record_extracted(str)`, `progress_updated(int, int)`, `extraction_cancelled()`, `extraction_failed(str, str)`) that the shell receives on the main thread via the normal signal-slot mechanism.
- Cancel is implemented by setting a shared `threading.Event` that the worker checks between records; the worker then emits `extraction_cancelled()` and exits cleanly.
- This avoids asyncio-Qt bridging complexity and keeps all UI updates on the main thread.

Alternative considered:
- `QThreadPool` / `QRunnable` without typed signals.
- Rejected because `QRunnable` does not support Qt signals natively; the typed-signal contract is essential for the UI wiring described in this change.

### Render PDF pages via PyMuPDF into `QPixmap`, display in a `QScrollArea`
- PyMuPDF (`fitz`) renders each page to a pixel matrix; the shell converts it to a `QImage`/`QPixmap` and paints highlight overlays for the selected record's bounding boxes using `QPainter`.
- The document panel uses a `QScrollArea` containing a `QLabel` (or a minimal `QWidget` subclass) to display the rendered page; scrolling is driven by Qt's native scroll mechanism.
- On record selection the panel renders the relevant page and scrolls to the highlighted region.

Alternative considered:
- Qt's built-in `QPdfView` (Qt 6.4+).
- Rejected because PyMuPDF is already a project dependency and provides the bounding-box data we need for highlight overlays; `QPdfView` would add a Qt version constraint.

### Display DOCX content in a read-only `QTextEdit`
- DOCX text (already extracted to Markdown during ingestion) is loaded into a `QTextEdit` with `setReadOnly(True)`.
- Highlight is applied using `QTextEdit`'s extra-selections API (`setExtraSelections`) on the character-offset range from `CoordinateAwareTextMap`.

Alternative considered:
- `QTextBrowser` (HTML-based rendering).
- Rejected because we already have plain Markdown text and the extra-selections API on `QTextEdit` is cleaner for programmatic highlight control.

### Settings dialog applies changes only on explicit Save; Cancel discards them
- The dialog makes a copy of `AppConfig` on open, edits the copy in-memory, and writes to disk only when the user confirms.
- Changes to `api_key_storage_mode` or the API key do **not** take effect in any running worker; they apply to the next job the user starts.

Alternative considered:
- Live-apply settings changes immediately.
- Rejected because changing the model or API key mid-extraction would produce inconsistent results within a single session.

### Export dialog is launched from the shell as a call into the export module
- The shell's Export toolbar action delegates to the export dialog flow defined in `add-export-capabilities`.
- In this change the Export action is wired but the dialog itself is owned by the export change; the shell imports it as a dependency.
- If the export module is not yet integrated, the Export action is shown but disabled with a tooltip "Export not available in this build."

## Risks / Trade-offs

- The shell touches many UI modules at once → Keep panel responsibilities narrow and use session state as the shared contract.
- Session restore and file-switch prompts can be easy to get wrong → Cover same-SHA reopen and different-SHA prompt behavior with tests.
- PDF rendering and highlight overlays can be heavy on large files → Keep rendering and highlight updates incremental; render only the visible page.
- `QThread`-based concurrency introduces cross-thread state mutation risk → Workers must not mutate `SessionState` directly; they emit signals carrying spell IDs or `LaxSpell` payloads, and the main-thread slot applies the mutation via the existing extraction API.

## Migration Plan

- No migration is required.

## Open Questions

- **Toolbar enable/disable rules for in-progress extraction**: Should all extraction toolbar actions (Detect Spells, Extract Selected, Extract All Pending) be disabled while any worker is running, or only the conflicting ones? Decision deferred to task 2.1; the safe default is to disable all extraction actions during any active worker run.
- **Focus prompt UI for Re-extract**: The spec requires a focus prompt string. A simple `QInputDialog.getText` call is sufficient for this change; a dedicated inline text field can be added later if UX feedback warrants it.
