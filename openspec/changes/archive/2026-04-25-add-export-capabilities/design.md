## Context

The revised spec defines export as a separate user flow with strict filtering and ordering rules. Export must read only committed canonical spell data, stay in sync across JSON and Markdown formats, and ignore session-only state such as pending records and dirty drafts.

This change depends on the canonical spell models and on record status semantics from earlier changes. It does not implement the broader UI shell beyond the export flow it needs.

## Goals / Non-Goals

**Goals:**
- Implement shared export filtering and ordering logic.
- Implement JSON v1.1 export with provenance fields and omitted internal fields.
- Implement Markdown export with the shared scope and clean-export filters.
- Warn users about dirty drafts before export.

**Non-Goals:**
- Implement document ingestion.
- Implement discovery or review editing.
- Implement packaging.

## Decisions

### Export reads committed canonical data only
- Export output must match committed app state, not work-in-progress drafts.
- This keeps exported files deterministic and avoids implicit save behavior.

Alternative considered:
- Auto-commit valid drafts during export.
- Rejected because export should not mutate user data.

### Keep one ordering and filtering path for JSON and Markdown
- The dialog rules should apply identically across both formats.
- One shared filter and order helper reduces drift between exporters.

Alternative considered:
- Let each exporter manage its own filtering.
- Rejected because the spec requires the formats to stay in sync.

### Strip internal ALT tags only at export time
- In-memory review notes can still keep machine-parseable alternatives during editing.
- Output files must remain human-facing.

Alternative considered:
- Strip ALT tags immediately on every edit.
- Rejected because re-extract merge behavior still needs them until commit or export.

## Risks / Trade-offs

- Export ordering can drift from UI expectations → Keep explicit persisted section order and separate temporary audit-sort behavior.
- JSON and Markdown can diverge over time → Use shared filter, scope, and note-cleanup helpers.
- Users can miss that drafts are excluded → Warn before export when dirty drafts exist.

## Migration Plan

- No migration is required.

## Open Questions

- None for this change.
