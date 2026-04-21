## Sequencing

- Implement after `add-core-session-models`, `add-document-ingestion-and-identity`, `add-discovery-and-pending-queue`, `add-stage2-extraction-and-review`, and `add-export-capabilities`.
- Treat this as the integration layer that consumes existing session, pipeline, review, and export behavior rather than defining them.

## 1. Main window and panel composition

- [ ] 1.1 Implement the `QMainWindow` shell, splitter layout, toolbar actions, progress bar, and status bar
- [ ] 1.2 Implement the document panel, three-section spell list panel, and right-side review or status host around `SessionState`

## 2. Session-aware UI flow

- [ ] 2.1 Wire worker signals, selection updates, and record highlighting across the panels
- [ ] 2.2 Implement the document-identity dialog, export-dialog launch, cancel flow, same-SHA restore, and different-SHA file-switch prompt behavior

## 3. Settings dialog

- [ ] 3.1 Implement the settings dialog, API-key test action, and binding to `AppConfig`
- [ ] 3.2 Add tests for settings persistence and session-aware file-open behavior
