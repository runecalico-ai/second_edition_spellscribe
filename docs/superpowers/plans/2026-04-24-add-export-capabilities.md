# Add Export Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build pure export support for SpellScribe so committed canonical spells can be exported to JSON v1.1 and Markdown with shared scope, filtering, ordering, and atomic-write behavior, while persisting the last-used export scope in `AppConfig`.

**Architecture:** Add a new pure-data module at `app/pipeline/export.py`. It will use `SpellRecord` inputs only for scope filtering and ordering helpers, then serialize ordered `Spell` objects through a JSON writer or a Jinja2-backed Markdown renderer. Reuse the existing atomic file-write patterns from `app/config.py` and `app/session.py`, and reuse `strip_alt_tags()` for human-facing note cleanup while keeping dirty-draft inspection and path selection in the future UI layer.

**Tech Stack:** Python 3.12, unittest, Pydantic v2 models, Jinja2 templates, existing atomic file I/O helpers.

---

## Spec Guardrails

- Export only committed `canonical_spell` values.
- Never export `draft_spell`, even when `draft_dirty` is true.
- Exclude `pending_extraction` records for every scope.
- `ExportScope` values must be `CONFIRMED_ONLY`, `NEEDS_REVIEW_ONLY`, and `EVERYTHING_EXTRACTED`.
- Confirmed-only and needs-review-only ordering must use `SpellRecord.section_order`.
- Everything-extracted ordering must use `Spell.extraction_start_line`, with `-1` values sorted last and `name.casefold()` as the tie-breaker.
- `clean_only=True` must exclude spells where `needs_review` is true, but it must keep confirmed spells that still have non-empty human-facing `review_notes`.
- JSON output must use the v1.1 envelope fields `version`, `exported_at`, `spellscribe_version`, and `spells`.
- JSON must omit `confidence`, `extraction_start_line`, and `extraction_end_line`, and it must omit `sphere` entirely for Wizard spells.
- JSON `tradition` must come from the existing computed `Spell.tradition` property, which is derived from `class_list` and yields `Arcane` for Wizard spells and `Divine` for Priest spells; do not add a new model field for export.
- Markdown must render `Cantrip` for Wizard level `0` and `Quest` for Priest level `8`.
- Both writers must strip ALT tags through `strip_alt_tags()` and write atomically using a sibling `.tmp` file, `fsync()`, and `os.replace()`.
- `AppConfig.last_export_scope` must default to `"everything_extracted"` and preserve unknown future string values on load.
- UI dialog behaviors from the spec are intentionally deferred to `add-desktop-shell-and-settings`; this plan keeps the exporter APIs pure and captures the future caller contract below.

## File Map

- Modify: `app/__init__.py`
- Modify: `app/config.py`
- Modify: `requirements.txt`
- Create: `app/pipeline/export.py`
- Create: `resources/templates/spell.md.j2`
- Create: `tests/test_pipeline_export.py`
- Modify: `tests/test_app_config.py`

## API Decisions Locked In By This Plan

- `filter_records(records: list[SpellRecord], scope: ExportScope) -> list[Spell]`
  Returns committed canonical spells in source-list order after scope filtering.
- `order_spells(records: list[SpellRecord], scope: ExportScope) -> list[Spell]`
  Returns committed canonical spells in export order. This keeps `section_order` access inside the helper because that metadata does not exist on `Spell`.
- Usage note: callers preparing final export output should pass `order_spells(records, scope)` into `to_json()` or `to_markdown()`. Keep `filter_records()` for callers that only need scope filtering without export ordering.
- `to_json(spells: list[Spell], path: str | Path, *, clean_only: bool, exported_at: str, spellscribe_version: str) -> None`
- `to_markdown(spells: list[Spell], path: str | Path, *, clean_only: bool) -> None`
- Add a private `_filter_clean_only(spells: list[Spell], clean_only: bool) -> list[Spell]` so both writers share the same post-scope filter.
- Add a private `_write_text_atomic(path: Path, text: str) -> None` so JSON and Markdown use identical durability behavior.

### Task 1: Add Version, Config, and Dependency Prerequisites

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/config.py`
- Modify: `requirements.txt`
- Modify: `tests/test_app_config.py`

- [x] **Step 1: Write the failing config tests**

Note: `AppConfig.from_dict()` already exists in `app/config.py`; these tests should exercise that loader instead of introducing a second config parser.

Note: `AppConfig.normalized()` returns an `AppConfig` instance, so the sample assertion intentionally uses attribute access (`defaults.last_export_scope`) instead of dict indexing.

Add these tests to `tests/test_app_config.py` in the existing normalization and persistence classes:

```python
    def test_last_export_scope_uses_default_for_blank_values(self) -> None:
        defaults = AppConfig().normalized()

        for raw_value in (None, 123, "", "   "):
            with self.subTest(raw_value=raw_value):
                config = AppConfig.from_dict({"last_export_scope": raw_value})
                self.assertEqual(config.last_export_scope, defaults.last_export_scope)

    def test_last_export_scope_round_trips_and_preserves_unknown_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config = AppConfig(last_export_scope="future_scope")

            config.save(config_path)
            loaded = AppConfig.load(config_path)

        self.assertEqual(loaded.last_export_scope, "future_scope")
```

- [x] **Step 2: Run the config tests to verify they fail**

Run: `python -m unittest tests.test_app_config -v`
Expected: FAIL because `AppConfig` does not yet define `last_export_scope` and `normalized()` does not preserve it.

- [x] **Step 3: Implement the minimal prerequisite changes**

Extend the existing `AppConfig` dataclass, `normalized()`, and `from_dict()` implementations in place, then add the Jinja2 dependency.

Note: `AppConfig.from_dict()` and `_coerce_non_blank_string()` already exist in `app/config.py`; reuse those helpers instead of reimplementing config loading or string coercion. The snippets below show only the exact additions inside existing code.

```python
# app/__init__.py
"""Application package for SpellScribe."""

__version__ = "1.0.0"
```

```python
# app/config.py
# In the existing AppConfig dataclass, add:
last_export_scope: str = "everything_extracted"

# In the existing normalized() method, add this keyword argument alongside the
# other string fields that already use _coerce_non_blank_string():
last_export_scope=_coerce_non_blank_string(
    self.last_export_scope,
    default="everything_extracted",
)

# In the existing from_dict() loader mapping, normalize through the existing
# string helper so blank or invalid values fall back while unknown future
# scopes still survive round-trips:
last_export_scope=_coerce_non_blank_string(
    data.get("last_export_scope"),
    default="everything_extracted",
)
```

```text
# requirements.txt
Add: jinja2>=3.1,<4
```

- [x] **Step 4: Re-run the config tests to verify they pass**

Run: `python -m unittest tests.test_app_config -v`
Expected: PASS, including the new `last_export_scope` assertions.

- [x] **Step 5: Commit the prerequisite change**

```bash
git add app/__init__.py app/config.py requirements.txt tests/test_app_config.py
git commit -m "feat: add export config prerequisites"
```

### Task 2: Add Export Helper Tests and Shared Record Selection Logic

**Files:**
- Create: `app/pipeline/export.py`
- Create: `tests/test_pipeline_export.py`

- [x] **Step 1: Write the failing helper tests**

Note: this builder intentionally feeds repo-supported input aliases such as `school`, `sphere`, and string `components`; `Spell.model_validate()` already normalizes them. Keep exporter-side component rendering defensive and convert components to display strings instead of assuming every item exposes `.value`.

Note: the current `Spell` model stores these validated string lists on the existing singular fields `spell.school` and `spell.sphere`. Keep using those names in exporter code and templates, and keep joining those string lists directly in Markdown; do not introduce pluralized field names or extra enum-extraction helpers for Markdown rendering.

Create `tests/test_pipeline_export.py` with builders that mirror the existing `Spell` and `SpellRecord` test style:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.models import ClassList, Spell
from app.pipeline.export import ExportScope, filter_records, order_spells
from app.session import SpellRecord, SpellRecordStatus


def _spell(
    *,
    name: str,
    class_list: ClassList = ClassList.WIZARD,
    level: int = 1,
    needs_review: bool = False,
    review_notes: str | None = None,
    extraction_start_line: int = 0,
) -> Spell:
    payload: dict[str, object] = {
        "name": name,
        "class_list": class_list,
        "level": level,
        "school": ["Evocation"] if class_list == ClassList.WIZARD else ["All"],
        "sphere": ["All"] if class_list == ClassList.PRIEST else None,
        "range": "30 yards",
        "components": ["V", "S"],
        "duration": "1 round",
        "casting_time": "1",
        "area_of_effect": "1 creature",
        "saving_throw": "None",
        "description": f"{name} description.",
        "source_document": "Player's Handbook",
        "source_page": 112,
        "needs_review": needs_review,
        "review_notes": review_notes,
        "extraction_start_line": extraction_start_line,
        "extraction_end_line": extraction_start_line + 4,
    }
    return Spell.model_validate(payload)


def _record(
    *,
    spell_id: str,
    status: SpellRecordStatus,
    section_order: int,
    canonical_spell: Spell | None = None,
    draft_spell: Spell | None = None,
    draft_dirty: bool = False,
    extraction_order: int = 0,
) -> SpellRecord:
    return SpellRecord(
        spell_id=spell_id,
        status=status,
        extraction_order=extraction_order,
        section_order=section_order,
        boundary_start_line=section_order,
        boundary_end_line=section_order,
        canonical_spell=canonical_spell,
        draft_spell=draft_spell,
        draft_dirty=draft_dirty,
    )


class ExportHelperTests(unittest.TestCase):
    def test_filter_records_excludes_pending_and_uses_canonical_only(self) -> None:
        canonical = _spell(name="Canonical", extraction_start_line=20)
        draft = _spell(name="Draft", extraction_start_line=99)
        records = [
            _record(
                spell_id="confirmed-1",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=canonical,
                draft_spell=draft,
                draft_dirty=True,
            ),
            _record(
                spell_id="pending-1",
                status=SpellRecordStatus.PENDING_EXTRACTION,
                section_order=0,
            ),
        ]

        spells = filter_records(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in spells], ["Canonical"])

    def test_order_spells_uses_section_order_for_confirmed_and_review(self) -> None:
        confirmed_records = [
            _record(
                spell_id="confirmed-b",
                status=SpellRecordStatus.CONFIRMED,
                section_order=2,
                canonical_spell=_spell(name="Second", extraction_start_line=50),
            ),
            _record(
                spell_id="confirmed-a",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="First", extraction_start_line=5),
            ),
        ]

        ordered = order_spells(confirmed_records, ExportScope.CONFIRMED_ONLY)

        self.assertEqual([spell.name for spell in ordered], ["First", "Second"])

    def test_order_spells_everything_extracted_uses_line_then_name(self) -> None:
        records = [
            _record(
                spell_id="spell-zeta",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Zeta", extraction_start_line=12),
            ),
            _record(
                spell_id="spell-alpha",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=1,
                canonical_spell=_spell(name="Alpha", extraction_start_line=12),
            ),
            _record(
                spell_id="spell-late",
                status=SpellRecordStatus.CONFIRMED,
                section_order=2,
                canonical_spell=_spell(name="Late", extraction_start_line=-1),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["Alpha", "Zeta", "Late"])
```

- [x] **Step 2: Run the export helper tests to verify they fail**

Run: `python -m unittest tests.test_pipeline_export.ExportHelperTests -v`
Expected: FAIL because `app.pipeline.export` does not exist yet.

- [x] **Step 3: Implement the shared helper module with minimal passing behavior**

Create `app/pipeline/export.py` and start with the enum, filtering helpers, and clean-only helper:

```python
from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path

from app.models import Spell
from app.session import SpellRecord, SpellRecordStatus
from app.utils.review_notes import strip_alt_tags


class ExportScope(str, Enum):
    CONFIRMED_ONLY = "confirmed_only"
    NEEDS_REVIEW_ONLY = "needs_review_only"
    EVERYTHING_EXTRACTED = "everything_extracted"


def filter_records(records: list[SpellRecord], scope: ExportScope) -> list[Spell]:
    selected: list[Spell] = []
    for record in records:
        if record.status == SpellRecordStatus.PENDING_EXTRACTION:
            continue
        if scope == ExportScope.CONFIRMED_ONLY and record.status != SpellRecordStatus.CONFIRMED:
            continue
        if scope == ExportScope.NEEDS_REVIEW_ONLY and record.status != SpellRecordStatus.NEEDS_REVIEW:
            continue
        if record.canonical_spell is None:
            continue
        selected.append(record.canonical_spell)
    return selected


def order_spells(records: list[SpellRecord], scope: ExportScope) -> list[Spell]:
    candidates = [
        record
        for record in records
        if record.status != SpellRecordStatus.PENDING_EXTRACTION and record.canonical_spell is not None
    ]
    if scope == ExportScope.CONFIRMED_ONLY:
        candidates = [record for record in candidates if record.status == SpellRecordStatus.CONFIRMED]
        candidates.sort(key=lambda record: record.section_order)
        return [record.canonical_spell for record in candidates if record.canonical_spell is not None]
    if scope == ExportScope.NEEDS_REVIEW_ONLY:
        candidates = [record for record in candidates if record.status == SpellRecordStatus.NEEDS_REVIEW]
        candidates.sort(key=lambda record: record.section_order)
        return [record.canonical_spell for record in candidates if record.canonical_spell is not None]

    spells = [record.canonical_spell for record in candidates if record.canonical_spell is not None]
    spells.sort(
        key=lambda spell: (
            spell.extraction_start_line == -1,
            spell.extraction_start_line,
            spell.name.casefold(),
        )
    )
    return spells


def _filter_clean_only(spells: list[Spell], clean_only: bool) -> list[Spell]:
    if not clean_only:
        return list(spells)
    return [spell for spell in spells if not spell.needs_review]


def to_json(
    spells: list[Spell],
    path: str | Path,
    *,
    clean_only: bool,
    exported_at: str,
    spellscribe_version: str,
) -> None:
    raise NotImplementedError


def to_markdown(
    spells: list[Spell],
    path: str | Path,
    *,
    clean_only: bool,
) -> None:
    raise NotImplementedError
```

- [x] **Step 4: Re-run the helper tests to verify they pass**

Run: `python -m unittest tests.test_pipeline_export.ExportHelperTests -v`
Expected: PASS for the scope filtering and ordering helpers.

- [x] **Step 5: Commit the helper-layer change**

```bash
git add app/pipeline/export.py tests/test_pipeline_export.py
git commit -m "feat: add export scope helpers"
```

### Task 3: Implement JSON Export Serialization and Atomic Writes

**Files:**
- Modify: `app/pipeline/export.py`
- Modify: `tests/test_pipeline_export.py`

- [x] **Step 1: Add failing JSON writer tests**

Note: the `tradition` assertions below refer to the existing computed `Spell.tradition` property derived from `class_list` (`Arcane` for Wizard, `Divine` for Priest); the serializer should copy that computed value into the export payload instead of adding a new schema field.

Extend `tests/test_pipeline_export.py` with JSON contract coverage:

```python
import json
import re
from datetime import datetime, timezone

from app import __version__
from app.models import ClassList
from app.pipeline.export import to_json


class ExportJsonTests(unittest.TestCase):
    def test_to_json_writes_v1_1_envelope_and_omits_internal_fields(self) -> None:
        spells = [
            _spell(
                name="Magic Missile",
                class_list=ClassList.WIZARD,
                level=1,
                review_notes="Manual note ALT[level]=2",
                extraction_start_line=2,
            ),
            _spell(
                name="Quest",
                class_list=ClassList.PRIEST,
                level=8,
                review_notes="ALT[level]=8",
                extraction_start_line=9,
            ),
        ]

        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "spells.json"
            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at=exported_at,
                spellscribe_version=__version__,
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["version"], "1.1")
        self.assertTrue(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["exported_at"]))
        self.assertEqual(payload["spellscribe_version"], __version__)
        self.assertEqual(payload["spells"][0]["tradition"], "Arcane")
        self.assertNotIn("confidence", payload["spells"][0])
        self.assertNotIn("extraction_start_line", payload["spells"][0])
        self.assertNotIn("extraction_end_line", payload["spells"][0])
        self.assertNotIn("sphere", payload["spells"][0])
        self.assertEqual(payload["spells"][0]["review_notes"], "Manual note")
        self.assertIsNone(payload["spells"][1]["review_notes"])
        self.assertEqual(payload["spells"][1]["sphere"], ["All"])

    def test_to_json_clean_only_and_empty_export_behaviour(self) -> None:
        spells = [
            _spell(name="Review Spell", needs_review=True, extraction_start_line=3),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "clean.json"
            to_json(
                spells,
                export_path,
                clean_only=True,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["spells"], [])

    def test_to_json_clean_only_keeps_confirmed_spell_with_cleaned_review_notes(self) -> None:
        spells = [
            _spell(
                name="Confirmed Note",
                needs_review=False,
                review_notes="Keep this ALT[level]=3",
                extraction_start_line=4,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "confirmed-notes.json"
            to_json(
                spells,
                export_path,
                clean_only=True,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual([spell["name"] for spell in payload["spells"]], ["Confirmed Note"])
        self.assertEqual(payload["spells"][0]["review_notes"], "Keep this")

    def test_to_json_uses_atomic_write_without_leaving_tmp_files(self) -> None:
        spells = [_spell(name="Atomic", extraction_start_line=1)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.json"
            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            leftover = list(export_path.parent.glob("*.tmp"))

        self.assertEqual(leftover, [])
```

- [x] **Step 2: Run the JSON tests to verify they fail**

Run: `python -m unittest tests.test_pipeline_export.ExportJsonTests -v`
Expected: FAIL because `to_json()` still raises `NotImplementedError`.

- [x] **Step 3: Implement the JSON serializer and shared atomic writer**

Add private helpers to `app/pipeline/export.py` so JSON and Markdown can share note cleanup and atomic I/O:

Note: `strip_alt_tags()` is the existing cleanup helper from `app.utils.review_notes`, and `Spell.tradition` is the existing computed property on `Spell`. Reuse both; this step does not add a new field to the model layer.

```python
def _normalized_review_notes(review_notes: str | None) -> str | None:
    cleaned = strip_alt_tags(review_notes or "").strip()
    return cleaned or None


def _spell_to_json_dict(spell: Spell) -> dict[str, object]:
    payload = spell.model_dump(mode="json")
    payload["tradition"] = spell.tradition.value
    payload["review_notes"] = _normalized_review_notes(spell.review_notes)
    payload.pop("confidence", None)
    payload.pop("extraction_start_line", None)
    payload.pop("extraction_end_line", None)
    if spell.class_list.value == "Wizard":
        payload.pop("sphere", None)
    return payload


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise


def to_json(
    spells: list[Spell],
    path: str | Path,
    *,
    clean_only: bool,
    exported_at: str,
    spellscribe_version: str,
) -> None:
    filtered = _filter_clean_only(spells, clean_only)
    payload = {
        "version": "1.1",
        "exported_at": exported_at,
        "spellscribe_version": spellscribe_version,
        "spells": [_spell_to_json_dict(spell) for spell in filtered],
    }
    destination = Path(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    _write_text_atomic(destination, serialized)
```

- [x] **Step 4: Re-run the JSON tests to verify they pass**

Run: `python -m unittest tests.test_pipeline_export.ExportJsonTests -v`
Expected: PASS, including the empty-export and no-leftover-`.tmp` assertions.

- [x] **Step 5: Commit the JSON export change**

```bash
git add app/pipeline/export.py tests/test_pipeline_export.py
git commit -m "feat: add json export writer"
```

### Task 4: Implement Markdown Rendering and Template Output

**Files:**
- Modify: `app/pipeline/export.py`
- Create: `resources/templates/spell.md.j2`
- Modify: `tests/test_pipeline_export.py`

- [x] **Step 1: Add failing Markdown tests**

Extend `tests/test_pipeline_export.py` with Markdown coverage:

```python
from app.pipeline.export import to_markdown


class ExportMarkdownTests(unittest.TestCase):
    def test_to_markdown_strips_alt_tags_and_renders_review_section(self) -> None:
        spells = [
            _spell(
                name="Review Spell",
                needs_review=True,
                review_notes="Human note ALT[level]=2",
                extraction_start_line=1,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "spells.md"
            to_markdown(spells, export_path, clean_only=False)
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("## Review Spell", content)
        self.assertIn("### Review", content)
        self.assertIn("Human note", content)
        self.assertNotIn("ALT[", content)

    def test_to_markdown_uses_cantrip_and_quest_labels(self) -> None:
        spells = [
            _spell(name="Cantrip Spell", class_list=ClassList.WIZARD, level=0, extraction_start_line=1),
            _spell(name="Quest Spell", class_list=ClassList.PRIEST, level=8, extraction_start_line=2),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "levels.md"
            to_markdown(spells, export_path, clean_only=False)
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("Level: Cantrip", content)
        self.assertIn("Level: Quest", content)

    def test_to_markdown_clean_only_excludes_needs_review_spells(self) -> None:
        spells = [
            _spell(name="Review Spell", needs_review=True, extraction_start_line=1),
            _spell(name="Clean Spell", needs_review=False, extraction_start_line=2),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "clean.md"
            to_markdown(spells, export_path, clean_only=True)
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("Clean Spell", content)
        self.assertNotIn("Review Spell", content)

    def test_to_markdown_empty_export_writes_empty_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "empty.md"
            to_markdown([], export_path, clean_only=False)
            content = export_path.read_text(encoding="utf-8")

        self.assertEqual(content.strip(), "")
```

- [x] **Step 2: Run the Markdown tests to verify they fail**

Run: `python -m unittest tests.test_pipeline_export.ExportMarkdownTests -v`
Expected: FAIL because `to_markdown()` still raises `NotImplementedError` and the template does not exist.

- [x] **Step 3: Create the Jinja2 template and Markdown renderer**

Create `resources/templates/spell.md.j2` with a stable, testable format:

```jinja2
## {{ spell.name }}

- Tradition: {{ spell.tradition.value }}
- Class: {{ spell.class_list.value }}
- Level: {{ level_label }}
- School: {{ spell.school | join(", ") }}
{% if spell.sphere %}- Sphere: {{ spell.sphere | join(", ") }}
{% endif %}- Range: {{ spell.range }}
- Components: {{ component_values | join(", ") }}
- Duration: {{ spell.duration }}
- Casting Time: {{ spell.casting_time }}
- Area of Effect: {{ spell.area_of_effect }}
- Saving Throw: {{ spell.saving_throw }}
- Source: {{ spell.source_document }}{% if spell.source_page is not none %}, p. {{ spell.source_page }}{% endif %}

{{ spell.description }}
{% if spell.needs_review or review_notes %}

### Review
{% if spell.needs_review %}
Needs review before publication.
{% endif %}
{% if review_notes %}
{{ review_notes }}
{% endif %}
{% endif %}
```

Then implement the renderer in `app/pipeline/export.py`:

Note: keep Markdown component rendering aligned with the Task 2 builder by converting validated component entries to display strings in Python. Do not assume every `spell.components` item exposes `.value`.

Note: `_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "resources" / "templates"` is the correct lookup for the current source-tree layout. If packaged builds need a different template-discovery strategy later, handle that in the separate `add-windows-packaging` change rather than in this export change.

```python
from jinja2 import Environment, FileSystemLoader


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "resources" / "templates"


def _level_label(spell: Spell) -> str | int:
    if spell.class_list.value == "Wizard" and spell.level == 0:
        return "Cantrip"
    if spell.class_list.value == "Priest" and spell.level == 8:
        return "Quest"
    return spell.level


def _component_values(spell: Spell) -> list[str]:
    return [str(getattr(component, "value", component)) for component in spell.components]


def _markdown_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def to_markdown(
    spells: list[Spell],
    path: str | Path,
    *,
    clean_only: bool,
) -> None:
    filtered = _filter_clean_only(spells, clean_only)
    if not filtered:
        _write_text_atomic(Path(path), "")
        return

    template = _markdown_environment().get_template("spell.md.j2")
    chunks = [
        template.render(
            spell=spell,
            review_notes=_normalized_review_notes(spell.review_notes),
            level_label=_level_label(spell),
            component_values=_component_values(spell),
        ).strip()
        for spell in filtered
    ]
    _write_text_atomic(Path(path), "\n\n".join(chunks))
```

- [x] **Step 4: Re-run the Markdown tests to verify they pass**

Run: `python -m unittest tests.test_pipeline_export.ExportMarkdownTests -v`
Expected: PASS, including ALT stripping, Cantrip and Quest labels, clean-only filtering, and empty-file behavior.

- [x] **Step 5: Commit the Markdown export change**

```bash
git add app/pipeline/export.py resources/templates/spell.md.j2 tests/test_pipeline_export.py
git commit -m "feat: add markdown export writer"
```

### Task 5: Run the Focused Verification Sweep and Spec Coverage Audit

**Files:**
- Modify: `tests/test_pipeline_export.py`
- Modify: `app/pipeline/export.py`

- [x] **Step 1: Add any missing focused tests before the final sweep**

Make sure `tests/test_pipeline_export.py` also covers these contract edges before the final run:

```python
    def test_order_spells_needs_review_scope_uses_section_order(self) -> None:
        records = [
            _record(
                spell_id="review-2",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=2,
                canonical_spell=_spell(name="Second", extraction_start_line=20),
            ),
            _record(
                spell_id="review-1",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=0,
                canonical_spell=_spell(name="First", extraction_start_line=10),
            ),
        ]

        ordered = order_spells(records, ExportScope.NEEDS_REVIEW_ONLY)

        self.assertEqual([spell.name for spell in ordered], ["First", "Second"])

    def test_to_json_keeps_integer_levels_in_payload(self) -> None:
        spells = [
            _spell(name="Cantrip Spell", class_list=ClassList.WIZARD, level=0, extraction_start_line=1),
            _spell(name="Quest Spell", class_list=ClassList.PRIEST, level=8, extraction_start_line=2),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "levels.json"
            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["spells"][0]["level"], 0)
        self.assertEqual(payload["spells"][1]["level"], 8)
```

- [x] **Step 2: Run the focused export and config tests**

Run: `python -m unittest tests.test_app_config tests.test_pipeline_export -v`
Expected: PASS for config persistence, export helpers, JSON export, and Markdown export.

- [x] **Step 3: Run the broader regression check for nearby behavior**

Run: `python -m unittest tests.test_session_state tests.test_review_notes -v`
Expected: PASS to confirm the export work did not break the session or review-note contracts it depends on.

- [x] **Step 4: Review the finished code against the spec guardrails in this document**

Confirm all of the following are true before closing the work:

```text
- JSON and Markdown both use the same scope and ordering helpers.
- Pending records are excluded in every scope.
- Export uses canonical spells only.
- Clean-only filtering is applied inside both writers.
- JSON omits Wizard sphere and internal extraction fields.
- Clean-only exports still keep confirmed spells whose cleaned `review_notes` remain non-empty.
- Markdown Review sections appear when needs_review is true or cleaned notes are present.
- Both writers leave no sibling .tmp file behind after success.
- AppConfig preserves unknown last_export_scope strings.
```

- [x] **Step 5: Commit the verification pass**

```bash
git add app/pipeline/export.py tests/test_pipeline_export.py
git commit -m "test: verify export capability contract"
```

## Deferred UI Integration Contract

Do not create placeholder `app/ui` modules in this change. The repository does not yet contain the desktop-shell files that will own the export dialog, and the spec already assigns those behaviors to `add-desktop-shell-and-settings`.

`AppConfig.export_directory` already exists in the current codebase and should be reused by that future shell layer. This export change adds only `AppConfig.last_export_scope`.

When the shell layer lands, its caller contract must be:

- Count dirty drafts from `SpellRecord.draft_dirty` before calling any writer, and show the blocking modal when the count is non-zero.
- Gather both JSON and Markdown output paths before writing either file.
- Use `AppConfig.default_source_document` with spaces replaced by underscores when proposing file names.
- Disable and uncheck the clean-only checkbox when the selected scope is `needs_review_only`.
- Show a non-blocking warning when the filtered spell list is empty, but still call the writers.
- Update `AppConfig.export_directory` and `AppConfig.last_export_scope` only after the full export succeeds.

## Spec Coverage Map

- Canonical-only export, pending exclusion, and clean-only filtering: Tasks 2, 3, and 4.
- Shared ordering rules for confirmed, needs-review, and everything-extracted scopes: Tasks 2 and 5.
- JSON v1.1 envelope, provenance, field omission, existing `Spell.tradition` export, and review-note normalization including the clean-only confirmed-note edge case: Task 3.
- Markdown ALT stripping, Review section behavior, Cantrip and Quest labels, and component string rendering from validated `Spell` objects: Task 4.
- `AppConfig.last_export_scope`, `app.__version__`, and Jinja2 prerequisite changes: Task 1.
- Atomic file-write behavior and no-leftover-`.tmp` files: Tasks 3, 4, and 5.
- UI dialog behaviors intentionally deferred to the future shell layer: Deferred UI Integration Contract.