## Sequencing

- Implement after `add-core-session-models` and `add-stage2-extraction-and-review`.
- Finish this before `add-desktop-shell-and-settings` if you want the shell change to wire a complete export flow without temporary stubs.

## 1. Shared export filtering and ordering

- [ ] 1.1 Implement shared scope, ordering, and clean-export filtering helpers for committed canonical spells
- [ ] 1.2 Add dirty-draft detection and warning behavior before export begins

## 2. Export renderers

- [ ] 2.1 Implement JSON v1.1 export with provenance fields and internal-field cleanup
- [ ] 2.2 Implement Markdown export and the Jinja2 template with shared filtering and review-note cleanup

## 3. Verification

- [ ] 3.1 Add tests for export scope ordering, pending-record exclusion, and dirty-draft warnings
- [ ] 3.2 Add tests for JSON and Markdown output parity and ALT-tag stripping
