<!-- Three-pass review conducted 2026-04-25 -->
<!-- Reviewer: Copilot (Claude Sonnet 4.6) -->
<!-- Source: tasks.md, specs/spell-export/spec.md, design.md -->
<!-- Scope: app/pipeline/export.py, app/__init__.py, app/config.py, resources/templates/spell.md.j2, tests/test_pipeline_export.py, tests/test_app_config.py -->
<!-- Remediation completed 2026-04-25 — all 3 findings resolved -->

## Summary
Total: 3 findings — 0 Critical, 0 High, 1 Medium, 2 Low — **all resolved 2026-04-25**

Spec completeness is excellent. All Tasks 1.1–1.5, 2.1–2.8, and 4.1–4.5 are fully implemented. Task 3 (UI dialog stubs) is correctly deferred to `add-desktop-shell-and-settings`. No missing implementations.

> **Note on prior review H-001:** The prior report rated the CRLF/newline issue as High (58) and cited "Task 3, Step 3" as the plan requirement. Tasks 3.3 in `tasks.md` concerns persisting config after export — not atomic writer line endings. No plan requirement mandates `newline="\n"` or a trailing newline in `_write_text_atomic`. The practical concern is real but the citation is wrong; re-triaged to Medium (M-001) below.

## Findings

### Critical
None.

### High
None.

### Medium
[M-001] (38) — `_write_text_atomic` writes CRLF on Windows; inconsistent with `AppConfig.save` pattern
Plan ref: Tasks 2.6 and 2.7 both route all file I/O through `_write_text_atomic`; `AppConfig.save` in the same codebase opens its temp file with `newline="\n"` for the identical atomic-replace pattern.
Location: `app/pipeline/export.py`, `_write_text_atomic()`, line ~128 (`os.fdopen(fd, "w", encoding="utf-8")`)
Detail: On Windows, `open(…, "w")` without `newline="\n"` translates `\n` → `\r\n`. Export tests still pass because `Path.read_text()` silently converts CRLF back to LF on read. However, the JSON and Markdown files actually written to disk will have CRLF line endings on Windows. This diverges from the established codebase convention (`AppConfig.save` uses `newline="\n"`) and can surprise downstream tools. Fix: add `newline="\n"` to the `os.fdopen` call.

> **FIXED 2026-04-25:** Added `newline="\n"` to `os.fdopen(fd, "w", encoding="utf-8", newline="\n")` in `_write_text_atomic`. Verified by three independent reviewer passes; no regressions.

### Low
[L-001] (20) — Name-based tie-break for all-`-1` extraction lines is not covered by tests
Plan ref: Task 4.1 requires "everything-extracted line-order with tie-break on `name`"; spec scenario "Everything-extracted uses merged line order" states spells missing `extraction_start_line` tie-break by `name` case-insensitive ascending.
Location: `tests/test_pipeline_export.py`, `ExportHelperTests` ordering section
Detail: `test_order_spells_everything_extracted_uses_line_then_case_insensitive_name` exercises the tie-break only when two spells share a positive line number (12). When `extraction_start_line == -1` the sort key substitutes `0` for the line component, so two `-1` spells rely solely on `name.casefold()` to break the tie — a distinct code path that is untested. The implementation is plausible but unverified for this sentinel case.

> **FIXED 2026-04-25:** Added `test_order_spells_everything_extracted_all_minus_one_lines_tie_break_on_name` to `ExportHelperTests`. Confirms two spells with `extraction_start_line=-1` sort by `name.casefold()`. All 37 export tests pass.

[L-002] (12) — `_spell_to_json_dict` redundantly overrides `tradition` already serialized by `model_dump`
Plan ref: Task 2.6 specifies the JSON output fields; `Spell.tradition` is a `@computed_field`, so `model_dump(mode="json")` already serializes it as its string value (e.g. `"Arcane"`, `"Divine"`).
Location: `app/pipeline/export.py`, `_spell_to_json_dict()`, line ~117 (`payload["tradition"] = spell.tradition.value`)
Detail: `model_dump(mode="json")` on Pydantic v2 includes computed fields and coerces `str`-enum values to their string representation. The explicit assignment after the dump is therefore a no-op in all current cases. While harmless, it suggests the serialization behavior of `computed_field` may not have been verified, and the redundancy could mask a future inconsistency if the field's serialization alias or mode ever changes. No code change is strictly required, but a comment or the line's removal would improve clarity.

> **FIXED 2026-04-25:** Removed the redundant `payload["tradition"] = spell.tradition.value` line from `_spell_to_json_dict`. `model_dump(mode="json")` already serializes the computed field. All 37 export tests pass.
