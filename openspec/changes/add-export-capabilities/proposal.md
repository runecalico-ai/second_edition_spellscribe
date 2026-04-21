## Why

Export rules are detailed enough to deserve their own change. Splitting export out keeps scope, ordering, filtering, and template behavior reviewable without mixing them with extraction or UI shell work.

## What Changes

- Add the shared export scope rules for confirmed-only, needs-review-only, and everything-extracted exports.
- Exclude pending records and dirty drafts from export output.
- Add the JSON v1.1 export envelope with provenance fields and stripped internal metadata.
- Add the Markdown export renderer and template.
- Add clean-export filtering and dirty-draft warnings.

## Capabilities

### New Capabilities
- `spell-export`: JSON and Markdown export with shared filtering, ordering, and review-note cleanup rules.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/pipeline/export.py`, `resources/templates/spell.md.j2`, `app/ui/**`, `tests/**`
- Affected behavior: export filtering, ordering, JSON payload shape, Markdown rendering, and pre-export warnings
- Dependencies: `jinja2`, canonical spell models, review-note helpers, session-state records
