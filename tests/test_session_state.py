from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.models import ClassList, CoordinateAwareTextMap, Spell, TextRegion
from app.session import (
    SessionState,
    SpellRecord,
    SpellRecordStatus,
    load_session_state,
    save_session_state,
)


SHA_SESSION = "f" * 64


def _spell_payload(
    *,
    name: str,
    level: int,
    start_line: int,
    end_line: int,
) -> dict[str, object]:
    return {
        "name": name,
        "class_list": ClassList.WIZARD,
        "level": level,
        "school": ["Evocation"],
        "range": "30 yards",
        "components": ["V", "S"],
        "duration": "1 round",
        "casting_time": "1",
        "area_of_effect": "1 creature",
        "saving_throw": "None",
        "description": f"{name} description.",
        "source_document": "Player's Handbook",
        "source_page": 112,
        "extraction_start_line": start_line,
        "extraction_end_line": end_line,
    }


def _canonical_spell(*, name: str = "Magic Missile", level: int = 1) -> Spell:
    return Spell.model_validate(
        _spell_payload(name=name, level=level, start_line=0, end_line=8)
    )


def _build_session_state() -> SessionState:
    canonical_spell = _canonical_spell(name="Magic Missile", level=1)
    draft_spell = _canonical_spell(name="Magic Missile", level=2)

    return SessionState(
        source_sha256_hex=SHA_SESSION,
        last_open_path=r"C:\\tmp\\spellbook.pdf",
        coordinate_map=CoordinateAwareTextMap(
            lines=[
                ("Magic Missile", TextRegion(page=0, bbox=(12.0, 20.0, 120.0, 34.0))),
                ("Damage", TextRegion(page=0, bbox=(16.0, 38.0, 160.0, 52.0))),
                ("Docx line", TextRegion(page=-1, char_offset=(42, 65))),
            ]
        ),
        records=[
            SpellRecord(
                spell_id="spell-001",
                status=SpellRecordStatus.CONFIRMED,
                extraction_order=0,
                section_order=0,
                boundary_start_line=0,
                boundary_end_line=9,
                context_heading="Wizard Spells",
                canonical_spell=canonical_spell,
            ),
            SpellRecord(
                spell_id="spell-002",
                status=SpellRecordStatus.NEEDS_REVIEW,
                extraction_order=1,
                section_order=1,
                boundary_start_line=10,
                boundary_end_line=20,
                context_heading="Revised Spells",
                canonical_spell=canonical_spell,
                draft_spell=draft_spell,
                draft_dirty=True,
            ),
        ],
        selected_spell_id="spell-002",
    )


class SessionStateSerializationTests(unittest.TestCase):
    def test_session_state_json_compatible_round_trip(self) -> None:
        state = _build_session_state()

        payload = state.model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=True)
        restored_payload = json.loads(encoded)
        restored = SessionState.model_validate(restored_payload)

        self.assertEqual(restored.model_dump(mode="json"), payload)

    def test_save_and_load_session_state_round_trip_with_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            state = _build_session_state()

            saved_path = save_session_state(state, session_path=session_path)
            loaded = load_session_state(session_path=session_path)

            self.assertEqual(saved_path, session_path)
            self.assertIsNotNone(loaded)
            if loaded is None:
                self.fail("Expected session state to load from the file that was just saved.")
            self.assertEqual(loaded.model_dump(mode="json"), state.model_dump(mode="json"))

    def test_load_session_state_returns_none_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"

            loaded = load_session_state(session_path=session_path)

            self.assertIsNone(loaded)

    def test_load_session_state_quarantines_corrupt_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_contents = "{\"records\": ["
            session_path.write_text(original_contents, encoding="utf-8")

            loaded = load_session_state(session_path=session_path)

            self.assertIsNone(loaded)
            self._assert_quarantine_result(session_path, original_contents)

    def test_load_session_state_quarantines_invalid_schema_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_contents = json.dumps(
                {
                    "version": "1",
                    "source_sha256_hex": "not-a-sha",
                    "last_open_path": "book.pdf",
                    "coordinate_map": {"lines": []},
                    "records": [],
                }
            )
            session_path.write_text(original_contents, encoding="utf-8")

            loaded = load_session_state(session_path=session_path)

            self.assertIsNone(loaded)
            self._assert_quarantine_result(session_path, original_contents)

    def test_load_session_state_accepts_supported_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            payload = _build_session_state().model_dump(mode="json")
            payload["version"] = "1"
            session_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_session_state(session_path=session_path)

            self.assertIsNotNone(loaded)
            if loaded is None:
                self.fail("Expected session with supported version to load.")
            self.assertEqual(loaded.version, "1")

    def test_load_session_state_quarantines_unsupported_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            payload = _build_session_state().model_dump(mode="json")
            payload["version"] = "2"
            original_contents = json.dumps(payload)
            session_path.write_text(original_contents, encoding="utf-8")

            loaded = load_session_state(session_path=session_path)

            self.assertIsNone(loaded)
            self._assert_quarantine_result(session_path, original_contents)

    def _assert_quarantine_result(self, session_path: Path, original_contents: str) -> None:
        self.assertFalse(session_path.exists())
        quarantine_candidates = list(session_path.parent.glob(f"{session_path.name}.bad.*"))
        self.assertEqual(len(quarantine_candidates), 1)

        quarantine_path = quarantine_candidates[0]
        self.assertTrue(quarantine_path.name.startswith(f"{session_path.name}.bad."))
        self.assertGreater(len(quarantine_path.name), len(f"{session_path.name}.bad."))
        self.assertEqual(quarantine_path.parent, session_path.parent)
        self.assertEqual(quarantine_path.read_text(encoding="utf-8"), original_contents)


class SpellRecordValidationTests(unittest.TestCase):
    def _record_payload(self) -> dict[str, object]:
        return {
            "spell_id": "spell-001",
            "status": SpellRecordStatus.PENDING_EXTRACTION,
            "extraction_order": 0,
            "section_order": 0,
            "boundary_start_line": 0,
            "boundary_end_line": 0,
        }

    def test_spell_record_allows_boundary_end_line_sentinel(self) -> None:
        payload = self._record_payload()
        payload["boundary_end_line"] = -1

        record = SpellRecord.model_validate(payload)

        self.assertEqual(record.boundary_end_line, -1)

    def test_spell_record_rejects_negative_extraction_order(self) -> None:
        payload = self._record_payload()
        payload["extraction_order"] = -1

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)

    def test_spell_record_rejects_negative_section_order(self) -> None:
        payload = self._record_payload()
        payload["section_order"] = -1

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)

    def test_spell_record_rejects_negative_boundary_start_line(self) -> None:
        payload = self._record_payload()
        payload["boundary_start_line"] = -1

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)

    def test_spell_record_rejects_boundary_end_line_before_start_line(self) -> None:
        payload = self._record_payload()
        payload["boundary_start_line"] = 5
        payload["boundary_end_line"] = 4

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)

    def test_spell_record_rejects_confirmed_without_canonical_spell(self) -> None:
        payload = self._record_payload()
        payload["status"] = SpellRecordStatus.CONFIRMED

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)

    def test_spell_record_allows_confirmed_with_canonical_spell(self) -> None:
        payload = self._record_payload()
        payload["status"] = SpellRecordStatus.CONFIRMED
        payload["canonical_spell"] = _canonical_spell(name="Confirmed Spell", level=3)

        record = SpellRecord.model_validate(payload)

        self.assertIsNotNone(record.canonical_spell)

    def test_spell_record_rejects_dirty_draft_without_draft_spell(self) -> None:
        payload = self._record_payload()
        payload["draft_dirty"] = True

        with self.assertRaises(ValidationError):
            SpellRecord.model_validate(payload)


class SessionStateInvariantTests(unittest.TestCase):
    def test_session_state_rejects_duplicate_spell_ids_in_records(self) -> None:
        payload = _build_session_state().model_dump(mode="python")
        payload["records"][1]["spell_id"] = payload["records"][0]["spell_id"]

        with self.assertRaises(ValidationError) as exc_info:
            SessionState.model_validate(payload)

        self.assertIn(
            "records must contain unique spell_id values",
            str(exc_info.exception),
        )

    def test_session_state_allows_unique_spell_ids_in_records(self) -> None:
        payload = _build_session_state().model_dump(mode="python")

        state = SessionState.model_validate(payload)
        record_ids = [record.spell_id for record in state.records]

        self.assertEqual(len(record_ids), len(set(record_ids)))

    def test_session_state_rejects_selected_spell_id_missing_from_records(self) -> None:
        payload = _build_session_state().model_dump(mode="python")
        payload["selected_spell_id"] = "missing-spell-id"

        with self.assertRaises(ValidationError):
            SessionState.model_validate(payload)

    def test_session_state_allows_unset_selected_spell_id(self) -> None:
        payload = _build_session_state().model_dump(mode="python")
        payload["selected_spell_id"] = None

        state = SessionState.model_validate(payload)

        self.assertIsNone(state.selected_spell_id)


if __name__ == "__main__":
    unittest.main()