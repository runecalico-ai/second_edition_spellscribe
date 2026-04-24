## Sequencing

- Implement after `add-core-session-models` and `add-stage2-extraction-and-review`.
- Finish this before `add-desktop-shell-and-settings` if you want the shell change to wire a complete export flow without temporary stubs.

## 1. Shared export filtering and ordering

- [ ] 1.1 Define `ExportScope` enum with values `CONFIRMED_ONLY`, `NEEDS_REVIEW_ONLY`, `EVERYTHING_EXTRACTED` (not `ALL`) in `app/pipeline/export.py`
- [ ] 1.2 Implement shared scope filtering helper: returns committed canonical `Spell` objects for a given `ExportScope` from a list of `SpellRecord`s, excluding `pending_extraction` records and always reading `canonical_spell` (never `draft_spell`)
- [ ] 1.3 Implement shared ordering helper: Confirmed-only and Needs-review-only sort by `section_order`; `EVERYTHING_EXTRACTED` sorts by `extraction_start_line` ascending (missing/-1 values sort last), tie-break by `name` case-insensitive ascending
- [ ] 1.4 Implement clean-export filter: when `clean_only=True`, exclude spells where `needs_review == True`
- [ ] 1.5 Add dirty-draft detection helper (returns count of records with `draft_dirty == True`) in the UI export dialog layer (before calling `export.py`); `export.py` functions remain pure data functions with no session access

## 2. Prerequisites and renderers

- [ ] 2.1 Add `__version__ = "1.0.0"` constant to `app/__init__.py`
- [ ] 2.2 Add `last_export_scope: str = "everything_extracted"` field to `AppConfig` in `app/config.py`
- [ ] 2.3 Add `jinja2>=3.1,<4` to `requirements.txt`
- [ ] 2.4 Create `app/pipeline/export.py` with `ExportScope` enum and stub signatures for `filter_records()`, `order_spells()`, `to_json()`, and `to_markdown()`
- [ ] 2.5 Create `resources/templates/` directory and `resources/templates/spell.md.j2` (Jinja2 template file)
- [ ] 2.6 Implement `to_json()` in `app/pipeline/export.py`: accepts `spells: list[Spell]`, `path: str | Path`, `*, clean_only: bool, exported_at: str, spellscribe_version: str`; applies `clean_only` filter internally; writes v1.1 envelope with `version`, `exported_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `spellscribe_version` (from `app.__version__`), and `spells`; omits `confidence`, `extraction_start_line`, `extraction_end_line`; omits `sphere` for Wizard spells; strips ALT tags via `strip_alt_tags()` and normalizes empty/whitespace `review_notes` to `null`; uses `json.dump(..., ensure_ascii=False, indent=2)`; writes atomically (`.tmp` sibling → `fsync` → `os.replace()`)
- [ ] 2.7 Implement `to_markdown()` in `app/pipeline/export.py`: same signature pattern as `to_json()` (`spells: list[Spell]`, `path: str | Path`, `*, clean_only: bool`); applies `clean_only` filter internally; strips ALT tags via `strip_alt_tags()` and normalizes empty/whitespace `review_notes` to `None` before passing to template; renders each spell through `spell.md.j2`; writes atomically with `utf-8` encoding
- [ ] 2.8 Implement Jinja2 template `resources/templates/spell.md.j2`: render `Cantrip` for Wizard level 0, `Quest` for Priest level 8, integer otherwise; include Review subsection when `needs_review` is true or `review_notes` is non-empty (after ALT-tag strip)

## 3. UI dialog stubs (wired in `add-desktop-shell-and-settings`)

The following behaviors belong to the export dialog UI layer. Stub or note them here so the shell change has a complete contract:

- [ ] 3.1 Export dialog collects both JSON and Markdown output paths upfront before writing any file; cancelling the second path prompt aborts the entire export
- [ ] 3.2 Default filename for each format is `<AppConfig.default_source_document>.<ext>` (spaces → underscores) rooted in `AppConfig.export_directory`; file extension enforced by `QFileDialog` filter; overwrite confirmation delegated to native dialog
- [ ] 3.3 After successful export, write chosen directory back to `AppConfig.export_directory` and chosen scope to `AppConfig.last_export_scope`
- [ ] 3.4 Disable and uncheck the Clean export checkbox when scope is `NEEDS_REVIEW_ONLY`
- [ ] 3.5 When the filtered spell list is empty, show a non-blocking warning before writing (export still proceeds with empty envelope)
- [ ] 3.6 Dirty-draft modal: before export, if any record has `draft_dirty == True`, show blocking dialog with count, "Continue Export" / "Cancel" buttons

## 4. Verification

- [ ] 4.1 Add unit tests for pure `export.py` helpers: scope filtering, ordering (confirmed-order, needs-review-order, everything-extracted line-order with tie-break on `name`), pending-record exclusion, and clean-export filtering
- [ ] 4.2 Add tests for JSON output: v1.1 envelope fields; `exported_at` matches `YYYY-MM-DDTHH:MM:SSZ` format; `spellscribe_version` equals `app.__version__`; `confidence`/`extraction_start_line`/`extraction_end_line` absent; `tradition` field present; Wizard `sphere` absent; Priest `sphere` present; `level` serialized as integer (0 for Cantrip, 8 for Quest — not string labels); `review_notes` is `null` when `strip_alt_tags()` returns empty
- [ ] 4.3 Add tests for Markdown output: ALT-tag stripping via `strip_alt_tags()`; Cantrip/Quest level labels rendered correctly; Review subsection present when `needs_review` true or `review_notes` non-empty; Review subsection absent when both are false/None; output excludes spells filtered by `clean_only`
- [ ] 4.4 Add test for atomic write: verify no `.tmp` file remains after a successful write and the final output file has correct content; verify both JSON and Markdown use `utf-8` encoding
- [ ] 4.5 Add test for `AppConfig` round-trip: `last_export_scope` is saved and loaded correctly; unknown scope string values are preserved (no enum coercion error on load)
- [ ] 4.6 Note: dirty-draft warning dialog, path defaults, scope persistence UI, and clean-export checkbox disable are UI integration concerns tested in `add-desktop-shell-and-settings`
