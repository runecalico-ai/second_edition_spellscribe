from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import __version__
from app.models import ClassList, Spell
from app.pipeline.export import (
    _filter_clean_only,
    ExportScope,
    filter_records,
    order_spells,
    to_json,
    to_markdown,
)
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
        "school": ["Evocation"],
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
    def test_filter_clean_only_returns_copy_when_disabled(self) -> None:
        spells = [
            _spell(name="Clean", extraction_start_line=10),
            _spell(name="Review", needs_review=True, extraction_start_line=20),
        ]

        filtered = _filter_clean_only(spells, clean_only=False)

        self.assertEqual(filtered, spells)
        self.assertIsNot(filtered, spells)

    def test_filter_clean_only_excludes_needs_review_when_enabled(self) -> None:
        spells = [
            _spell(name="Clean", extraction_start_line=10),
            _spell(name="Review", needs_review=True, extraction_start_line=20),
        ]

        filtered = _filter_clean_only(spells, clean_only=True)

        self.assertEqual([spell.name for spell in filtered], ["Clean"])

    def test_filter_clean_only_keeps_spell_with_review_notes_when_review_not_needed(self) -> None:
        spells = [
            _spell(
                name="Annotated Clean",
                needs_review=False,
                review_notes="Reviewer context retained for export.",
                extraction_start_line=10,
            )
        ]

        filtered = _filter_clean_only(spells, clean_only=True)

        self.assertEqual([spell.name for spell in filtered], ["Annotated Clean"])

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

    def test_filter_records_everything_extracted_preserves_source_order(self) -> None:
        records = [
            _record(
                spell_id="review-zeta",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=9,
                canonical_spell=_spell(name="Zeta Review", extraction_start_line=90),
            ),
            _record(
                spell_id="pending-1",
                status=SpellRecordStatus.PENDING_EXTRACTION,
                section_order=8,
            ),
            _record(
                spell_id="review-missing-canonical",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=7,
                draft_spell=_spell(name="Draft Only", extraction_start_line=70),
                draft_dirty=True,
            ),
            _record(
                spell_id="confirmed-alpha",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=_spell(name="Alpha", extraction_start_line=10),
            ),
            _record(
                spell_id="review-beta",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=0,
                canonical_spell=_spell(name="Beta Review", extraction_start_line=5),
            ),
        ]

        spells = filter_records(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in spells], ["Zeta Review", "Alpha", "Beta Review"])

    def test_filter_records_applies_scope_specific_status_filters(self) -> None:
        records = [
            _record(
                spell_id="confirmed-1",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Confirmed", extraction_start_line=10),
            ),
            _record(
                spell_id="review-1",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=1,
                canonical_spell=_spell(name="Review", extraction_start_line=20),
            ),
            _record(
                spell_id="pending-1",
                status=SpellRecordStatus.PENDING_EXTRACTION,
                section_order=2,
            ),
        ]

        confirmed_spells = filter_records(records, ExportScope.CONFIRMED_ONLY)
        review_spells = filter_records(records, ExportScope.NEEDS_REVIEW_ONLY)

        self.assertEqual([spell.name for spell in confirmed_spells], ["Confirmed"])
        self.assertEqual([spell.name for spell in review_spells], ["Review"])

    def test_filter_records_rejects_unsupported_scope(self) -> None:
        records = [
            _record(
                spell_id="confirmed-1",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Confirmed", extraction_start_line=10),
            )
        ]

        with self.assertRaises(ValueError):
            filter_records(records, "unsupported_scope")

    def test_filter_records_preserves_source_order_after_scope_filtering(self) -> None:
        records = [
            _record(
                spell_id="confirmed-zeta",
                status=SpellRecordStatus.CONFIRMED,
                section_order=9,
                canonical_spell=_spell(name="Zeta", extraction_start_line=90),
            ),
            _record(
                spell_id="review-zulu",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=8,
                canonical_spell=_spell(name="Zulu Review", extraction_start_line=80),
            ),
            _record(
                spell_id="pending-1",
                status=SpellRecordStatus.PENDING_EXTRACTION,
                section_order=7,
            ),
            _record(
                spell_id="confirmed-alpha",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=_spell(name="Alpha", extraction_start_line=10),
            ),
            _record(
                spell_id="review-beta",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=0,
                canonical_spell=_spell(name="Beta Review", extraction_start_line=5),
            ),
        ]

        confirmed_spells = filter_records(records, ExportScope.CONFIRMED_ONLY)
        review_spells = filter_records(records, ExportScope.NEEDS_REVIEW_ONLY)

        self.assertEqual([spell.name for spell in confirmed_spells], ["Zeta", "Alpha"])
        self.assertEqual([spell.name for spell in review_spells], ["Zulu Review", "Beta Review"])

    def test_order_spells_confirmed_only_excludes_needs_review_before_sorting(self) -> None:
        review_record = _record(
            spell_id="review-ignored",
            status=SpellRecordStatus.NEEDS_REVIEW,
            section_order=1,
            canonical_spell=_spell(name="Ignored Review", extraction_start_line=1),
        )
        review_record.section_order = "not-used-in-confirmed-scope"

        confirmed_records = [
            _record(
                spell_id="confirmed-b",
                status=SpellRecordStatus.CONFIRMED,
                section_order=2,
                canonical_spell=_spell(name="Second", extraction_start_line=50),
            ),
            review_record,
            _record(
                spell_id="confirmed-a",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="First", extraction_start_line=5),
            ),
        ]

        ordered = order_spells(confirmed_records, ExportScope.CONFIRMED_ONLY)

        self.assertEqual([spell.name for spell in ordered], ["First", "Second"])

    def test_order_spells_needs_review_only_excludes_confirmed_before_sorting(self) -> None:
        confirmed_record = _record(
            spell_id="confirmed-ignored",
            status=SpellRecordStatus.CONFIRMED,
            section_order=1,
            canonical_spell=_spell(name="Ignored Confirmed", extraction_start_line=1),
        )
        confirmed_record.section_order = "not-used-in-review-scope"

        review_records = [
            _record(
                spell_id="review-b",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=2,
                canonical_spell=_spell(name="Second", extraction_start_line=5),
            ),
            confirmed_record,
            _record(
                spell_id="review-a",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=0,
                canonical_spell=_spell(name="First", extraction_start_line=50),
            ),
        ]

        ordered = order_spells(review_records, ExportScope.NEEDS_REVIEW_ONLY)

        self.assertEqual([spell.name for spell in ordered], ["First", "Second"])

    def test_order_spells_everything_extracted_excludes_pending_and_non_canonical(self) -> None:
        records = [
            _record(
                spell_id="pending-with-canonical",
                status=SpellRecordStatus.PENDING_EXTRACTION,
                section_order=0,
                canonical_spell=_spell(name="Pending", extraction_start_line=1),
            ),
            _record(
                spell_id="draft-only",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=1,
                draft_spell=_spell(name="Draft Only", extraction_start_line=2),
                draft_dirty=True,
            ),
            _record(
                spell_id="missing-canonical",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=2,
            ),
            _record(
                spell_id="confirmed-kept",
                status=SpellRecordStatus.CONFIRMED,
                section_order=3,
                canonical_spell=_spell(name="Confirmed", extraction_start_line=5),
            ),
            _record(
                spell_id="review-kept",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=4,
                canonical_spell=_spell(name="Review", extraction_start_line=8),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["Confirmed", "Review"])

    def test_order_spells_rejects_unsupported_scope(self) -> None:
        records = [
            _record(
                spell_id="confirmed-1",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Confirmed", extraction_start_line=10),
            )
        ]

        with self.assertRaises(ValueError):
            order_spells(records, "unsupported_scope")

    def test_order_spells_everything_extracted_prefers_canonical_over_dirty_draft(self) -> None:
        canonical_spell = _spell(name="Canonical", extraction_start_line=40)
        draft_spell = _spell(name="Draft", extraction_start_line=5)
        records = [
            _record(
                spell_id="record-with-draft",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=1,
                canonical_spell=canonical_spell,
                draft_spell=draft_spell,
                draft_dirty=True,
            ),
            _record(
                spell_id="earlier-canonical",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Earlier", extraction_start_line=20),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["Earlier", "Canonical"])
        self.assertIs(ordered[1], canonical_spell)

    def test_order_spells_everything_extracted_uses_line_then_case_insensitive_name(self) -> None:
        records = [
            _record(
                spell_id="spell-zebra",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Zebra", extraction_start_line=12),
            ),
            _record(
                spell_id="spell-aardvark",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=1,
                canonical_spell=_spell(name="aardvark", extraction_start_line=12),
            ),
            _record(
                spell_id="spell-late",
                status=SpellRecordStatus.CONFIRMED,
                section_order=2,
                canonical_spell=_spell(name="Late", extraction_start_line=-1),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["aardvark", "Zebra", "Late"])

    def test_order_spells_everything_extracted_all_minus_one_lines_tie_break_on_name(self) -> None:
        records = [
            _record(
                spell_id="spell-zebra",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Zebra", extraction_start_line=-1),
            ),
            _record(
                spell_id="spell-aardvark",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=_spell(name="aardvark", extraction_start_line=-1),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["aardvark", "Zebra"])

class ExportMarkdownTests(unittest.TestCase):
    def test_to_markdown_strips_alt_tags_and_renders_review_section_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "spells.md"

            to_markdown(
                [
                    _spell(
                        name="Review Spell",
                        needs_review=True,
                        review_notes="Human note ALT[level]=2",
                        extraction_start_line=1,
                    )
                ],
                export_path,
                clean_only=False,
            )
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("## Review Spell", content)
        self.assertIn("### Review", content)
        self.assertIn("Human note", content)
        self.assertNotIn("ALT[", content)

    def test_to_markdown_renders_review_section_when_review_needed_but_notes_clean_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "needs-review.md"

            to_markdown(
                [
                    _spell(
                        name="Needs Review",
                        needs_review=True,
                        review_notes="ALT[level]=2",
                        extraction_start_line=1,
                    )
                ],
                export_path,
                clean_only=False,
            )
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("### Review", content)
        self.assertIn("Needs review before publication.", content)
        self.assertNotIn("ALT[", content)

    def test_to_markdown_omits_review_section_for_whitespace_only_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "whitespace-notes.md"

            to_markdown(
                [
                    _spell(
                        name="Whitespace Notes",
                        needs_review=False,
                        review_notes="  \n\t  ",
                        extraction_start_line=1,
                    )
                ],
                export_path,
                clean_only=False,
            )
            content = export_path.read_text(encoding="utf-8")

        self.assertNotIn("### Review", content)

    def test_to_markdown_renders_description_as_standalone_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "paragraphs.md"

            to_markdown(
                [_spell(name="Paragraph Spell", extraction_start_line=1)],
                export_path,
                clean_only=False,
            )
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("- Source: Player's Handbook, p. 112\n\nParagraph Spell description.", content)

    def test_to_markdown_renders_review_section_from_cleaned_notes_without_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "notes-only-review.md"

            to_markdown(
                [
                    _spell(
                        name="Annotated Spell",
                        needs_review=False,
                        review_notes="Carry this note ALT[level]=2",
                        extraction_start_line=1,
                    )
                ],
                export_path,
                clean_only=False,
            )
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("## Annotated Spell", content)
        self.assertIn("### Review", content)
        self.assertIn("Carry this note", content)
        self.assertNotIn("Needs review before publication.", content)
        self.assertNotIn("ALT[", content)

    def test_to_markdown_omits_review_section_when_review_not_needed_and_notes_clean_empty(self) -> None:
        for suffix, review_notes in (("none", None), ("empty", " ALT[level]=2 ")):
            with self.subTest(review_notes=review_notes):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    export_path = Path(tmp_dir) / f"no-review-{suffix}.md"

                    to_markdown(
                        [
                            _spell(
                                name="Clean Spell",
                                needs_review=False,
                                review_notes=review_notes,
                                extraction_start_line=1,
                            )
                        ],
                        export_path,
                        clean_only=False,
                    )
                    content = export_path.read_text(encoding="utf-8")

            self.assertIn("## Clean Spell", content)
            self.assertNotIn("### Review", content)
            self.assertNotIn("Needs review before publication.", content)

    def test_to_markdown_uses_cantrip_and_quest_labels(self) -> None:
        spells = [
            _spell(
                name="Cantrip Spell",
                class_list=ClassList.WIZARD,
                level=0,
                extraction_start_line=1,
            ),
            _spell(
                name="Quest Spell",
                class_list=ClassList.PRIEST,
                level=8,
                extraction_start_line=2,
            ),
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

    def test_to_markdown_preserves_non_ascii_content_across_utf_8_round_trip(self) -> None:
        spells = [
            _spell(
                name="Chant d'été",
                review_notes="Résumé pour naïve lecteurs",
                extraction_start_line=15,
            )
        ]
        spells[0].description = "Déchaîne la foudre sur São Paulo. Café déjà vu."
        spells[0].source_document = "Tome des Mystères"

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "utf-8.md"

            to_markdown(spells, export_path, clean_only=False)
            content = export_path.read_text(encoding="utf-8")

        self.assertIn("## Chant d'été", content)
        self.assertIn("Déchaîne la foudre sur São Paulo. Café déjà vu.", content)
        self.assertIn("- Source: Tome des Mystères, p. 112", content)
        self.assertIn("Résumé pour naïve lecteurs", content)

    def test_to_markdown_uses_atomic_write_without_leaving_tmp_files(self) -> None:
        spells = [_spell(name="Atomic Spell", extraction_start_line=3)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.md"

            to_markdown(spells, export_path, clean_only=False)

            siblings = sorted(path.name for path in export_path.parent.iterdir())

        self.assertEqual(siblings, ["atomic.md"])

    def test_to_markdown_does_not_corrupt_existing_file_when_replace_fails(self) -> None:
        spells = [_spell(name="Atomic Spell", extraction_start_line=3)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.md"
            original_contents = "existing markdown\n"
            export_path.write_text(original_contents, encoding="utf-8")

            with patch("app.pipeline.export.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OSError):
                    to_markdown(spells, export_path, clean_only=False)

            self.assertEqual(export_path.read_text(encoding="utf-8"), original_contents)
            self.assertEqual(sorted(path.name for path in export_path.parent.iterdir()), ["atomic.md"])

    def test_to_markdown_empty_export_writes_empty_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "empty.md"

            to_markdown([], export_path, clean_only=False)
            content = export_path.read_text(encoding="utf-8")

        self.assertEqual(content.strip(), "")


class ExportJsonTests(unittest.TestCase):

    def test_to_json_preserves_integer_level_boundaries_in_v1_1_envelope(self) -> None:
        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        spells = [
            _spell(
                name="Cantrip",
                class_list=ClassList.WIZARD,
                level=0,
                review_notes="Keep this note ALT[level]=2",
                extraction_start_line=12,
            ),
            _spell(
                name="Quest",
                class_list=ClassList.PRIEST,
                level=8,
                review_notes="ALT[level]=8",
                extraction_start_line=40,
            ),
        ]

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
        self.assertIsNotNone(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", exported_at))
        self.assertEqual(payload["exported_at"], exported_at)
        self.assertEqual(payload["spellscribe_version"], __version__)

        wizard_spell = payload["spells"][0]
        priest_spell = payload["spells"][1]

        self.assertEqual(wizard_spell["tradition"], "Arcane")
        self.assertEqual(priest_spell["tradition"], "Divine")
        self.assertNotIn("confidence", wizard_spell)
        self.assertNotIn("extraction_start_line", wizard_spell)
        self.assertNotIn("extraction_end_line", wizard_spell)
        self.assertNotIn("sphere", wizard_spell)
        self.assertEqual(priest_spell["sphere"], ["All"])
        self.assertEqual(wizard_spell["review_notes"], "Keep this note")
        self.assertIsNone(priest_spell["review_notes"])
        self.assertIsInstance(wizard_spell["level"], int)
        self.assertEqual(wizard_spell["level"], 0)
        self.assertIsInstance(priest_spell["level"], int)
        self.assertEqual(priest_spell["level"], 8)

    def test_to_json_preserves_non_ascii_content_across_utf_8_round_trip(self) -> None:
        spells = [
            _spell(
                name="Chant d'été",
                review_notes="Résumé pour naïve lecteurs",
                extraction_start_line=15,
            )
        ]
        spells[0].description = "Déchaîne la foudre sur São Paulo."
        spells[0].source_document = "Tome des Mystères"

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "utf-8.json"

            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T12:34:56Z",
                spellscribe_version=__version__,
            )

            serialized = export_path.read_text(encoding="utf-8")
            payload = json.loads(serialized)

        self.assertIn("Chant d'été", serialized)
        self.assertIn("São Paulo", serialized)
        self.assertEqual(payload["spells"][0]["name"], "Chant d'été")
        self.assertEqual(
            payload["spells"][0]["description"],
            "Déchaîne la foudre sur São Paulo.",
        )
        self.assertEqual(payload["spells"][0]["source_document"], "Tome des Mystères")
        self.assertEqual(
            payload["spells"][0]["review_notes"],
            "Résumé pour naïve lecteurs",
        )

    def test_to_json_clean_only_excludes_needs_review_but_keeps_clean_review_notes(self) -> None:
        spells = [
            _spell(
                name="Confirmed With Notes",
                needs_review=False,
                review_notes="Keep this context ALT[level]=3",
                extraction_start_line=5,
            ),
            _spell(
                name="Needs Review",
                needs_review=True,
                review_notes="Human follow-up needed",
                extraction_start_line=10,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "clean-only.json"

            to_json(
                spells,
                export_path,
                clean_only=True,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual([spell["name"] for spell in payload["spells"]], ["Confirmed With Notes"])
        self.assertEqual(payload["spells"][0]["review_notes"], "Keep this context")

    def test_to_json_writes_empty_v1_1_envelope_when_clean_only_filters_everything(self) -> None:
        spells = [
            _spell(
                name="Needs Review",
                needs_review=True,
                review_notes="Human follow-up needed",
                extraction_start_line=10,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "empty-clean-only.json"

            to_json(
                spells,
                export_path,
                clean_only=True,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload,
            {
                "version": "1.1",
                "exported_at": "2026-04-24T00:00:00Z",
                "spellscribe_version": "1.0.0",
                "spells": [],
            },
        )

    def test_to_json_normalizes_whitespace_only_review_notes_to_null(self) -> None:
        spells = [
            _spell(
                name="Whitespace Notes",
                review_notes="   \n\t  ",
                extraction_start_line=10,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "whitespace-review-notes.json"

            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            payload = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertIsNone(payload["spells"][0]["review_notes"])

    def test_to_json_uses_atomic_write_without_leaving_tmp_files(self) -> None:
        spells = [_spell(name="Atomic Spell", extraction_start_line=3)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.json"

            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            siblings = sorted(path.name for path in export_path.parent.iterdir())

        self.assertEqual(siblings, ["atomic.json"])

    def test_to_json_does_not_corrupt_existing_file_when_replace_fails(self) -> None:
        spells = [_spell(name="Atomic Spell", extraction_start_line=3)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.json"
            original_contents = '{"existing": true}\n'
            export_path.write_text(original_contents, encoding="utf-8")

            with patch("app.pipeline.export.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OSError):
                    to_json(
                        spells,
                        export_path,
                        clean_only=False,
                        exported_at="2026-04-24T00:00:00Z",
                        spellscribe_version="1.0.0",
                    )

            self.assertEqual(export_path.read_text(encoding="utf-8"), original_contents)
            self.assertEqual(sorted(path.name for path in export_path.parent.iterdir()), ["atomic.json"])

    def test_to_json_atomic_write_does_not_collide_with_existing_fixed_tmp_path(self) -> None:
        spells = [_spell(name="Atomic Spell", extraction_start_line=3)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = Path(tmp_dir) / "atomic.json"
            occupied_tmp_path = export_path.with_name(f"{export_path.name}.tmp")
            occupied_tmp_path.write_text("occupied", encoding="utf-8")

            to_json(
                spells,
                export_path,
                clean_only=False,
                exported_at="2026-04-24T00:00:00Z",
                spellscribe_version="1.0.0",
            )

            siblings = sorted(path.name for path in export_path.parent.iterdir())
            occupied_tmp_contents = occupied_tmp_path.read_text(encoding="utf-8")

        self.assertEqual(siblings, ["atomic.json", "atomic.json.tmp"])
        self.assertEqual(occupied_tmp_contents, "occupied")

    def test_order_spells_everything_extracted_treats_only_minus_one_as_missing(self) -> None:
        records = [
            _record(
                spell_id="spell-missing",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Missing", extraction_start_line=-1),
            ),
            _record(
                spell_id="spell-first",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=_spell(name="First", extraction_start_line=3),
            ),
            _record(
                spell_id="spell-second",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=2,
                canonical_spell=_spell(name="Second", extraction_start_line=7),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["First", "Second", "Missing"])

    def test_order_spells_everything_extracted_keeps_other_negative_lines_in_numeric_order(self) -> None:
        records = [
            _record(
                spell_id="spell-negative",
                status=SpellRecordStatus.CONFIRMED,
                section_order=0,
                canonical_spell=_spell(name="Negative", extraction_start_line=-2),
            ),
            _record(
                spell_id="spell-first",
                status=SpellRecordStatus.CONFIRMED,
                section_order=1,
                canonical_spell=_spell(name="First", extraction_start_line=3),
            ),
            _record(
                spell_id="spell-missing",
                status=SpellRecordStatus.NEEDS_REVIEW,
                section_order=2,
                canonical_spell=_spell(name="Missing", extraction_start_line=-1),
            ),
        ]

        ordered = order_spells(records, ExportScope.EVERYTHING_EXTRACTED)

        self.assertEqual([spell.name for spell in ordered], ["Negative", "First", "Missing"])