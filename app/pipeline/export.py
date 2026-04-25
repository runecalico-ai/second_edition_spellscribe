from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.models import Spell
from app.session import SpellRecord, SpellRecordStatus
from app.utils.review_notes import strip_alt_tags


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "resources" / "templates"


class ExportScope(str, Enum):
    CONFIRMED_ONLY = "confirmed_only"
    NEEDS_REVIEW_ONLY = "needs_review_only"
    EVERYTHING_EXTRACTED = "everything_extracted"


def _require_export_scope(scope: ExportScope) -> ExportScope:
    return ExportScope(scope)


def filter_records(records: list[SpellRecord], scope: ExportScope) -> list[Spell]:
    scope = _require_export_scope(scope)
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
    scope = _require_export_scope(scope)
    candidates = [
        record
        for record in records
        if record.status != SpellRecordStatus.PENDING_EXTRACTION
        and record.canonical_spell is not None
    ]

    if scope == ExportScope.CONFIRMED_ONLY:
        candidates = [
            record for record in candidates if record.status == SpellRecordStatus.CONFIRMED
        ]
        candidates.sort(key=lambda record: record.section_order)
        return [record.canonical_spell for record in candidates if record.canonical_spell is not None]

    if scope == ExportScope.NEEDS_REVIEW_ONLY:
        candidates = [
            record for record in candidates if record.status == SpellRecordStatus.NEEDS_REVIEW
        ]
        candidates.sort(key=lambda record: record.section_order)
        return [record.canonical_spell for record in candidates if record.canonical_spell is not None]

    spells = [record.canonical_spell for record in candidates if record.canonical_spell is not None]
    spells.sort(
        key=lambda spell: (
            spell.extraction_start_line == -1,
            spell.extraction_start_line if spell.extraction_start_line != -1 else 0,
            spell.name.casefold(),
        )
    )
    return spells


def _filter_clean_only(spells: list[Spell], clean_only: bool) -> list[Spell]:
    if not clean_only:
        return list(spells)
    return [spell for spell in spells if not spell.needs_review]


def _normalized_review_notes(review_notes: str | None) -> str | None:
    cleaned = strip_alt_tags(review_notes).strip()
    if not cleaned:
        return None
    return cleaned


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


def _spell_to_json_dict(spell: Spell) -> dict[str, object]:
    payload = spell.model_dump(mode="json")
    payload.pop("confidence", None)
    payload.pop("extraction_start_line", None)
    payload.pop("extraction_end_line", None)
    payload["review_notes"] = _normalized_review_notes(spell.review_notes)
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
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    _write_text_atomic(Path(path), serialized)


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