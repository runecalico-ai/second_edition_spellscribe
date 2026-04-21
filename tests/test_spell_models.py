from __future__ import annotations

import math
import unittest

from pydantic import ValidationError

from app.models import ClassList, LaxSpell, Spell


def _base_spell_payload() -> dict[str, object]:
    return {
        "name": "Sample Spell",
        "class_list": ClassList.WIZARD,
        "level": 1,
        "school": ["Evocation"],
        "range": "30 yards",
        "components": ["V", "S"],
        "duration": "1 round",
        "casting_time": "1",
        "area_of_effect": "1 creature",
        "saving_throw": "None",
        "description": "A sample spell description.",
        "source_document": "sample-source.pdf",
    }


class SpellModelValidationTests(unittest.TestCase):
    def test_wizard_cantrip_level_normalizes_to_zero(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.WIZARD
        payload["level"] = "Cantrip"

        spell = Spell.model_validate(payload)

        self.assertEqual(spell.level, 0)

    def test_priest_quest_level_normalizes_to_eight(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.PRIEST
        payload["level"] = "Quest"
        payload["sphere"] = ["All"]

        spell = Spell.model_validate(payload)

        self.assertEqual(spell.level, 8)

    def test_priest_spell_rejects_level_outside_supported_range(self) -> None:
        for level in (0, 9):
            with self.subTest(level=level):
                payload = _base_spell_payload()
                payload["class_list"] = ClassList.PRIEST
                payload["level"] = level
                payload["sphere"] = ["All"]

                with self.assertRaises(ValidationError) as context:
                    Spell.model_validate(payload)

                self.assertIn("Priest spell level must be 1-8", str(context.exception))

    def test_priest_spell_rejects_missing_or_empty_sphere(self) -> None:
        missing_sphere_payload = _base_spell_payload()
        missing_sphere_payload["class_list"] = ClassList.PRIEST
        missing_sphere_payload["level"] = 3

        empty_sphere_payload = _base_spell_payload()
        empty_sphere_payload["class_list"] = ClassList.PRIEST
        empty_sphere_payload["level"] = 3
        empty_sphere_payload["sphere"] = []

        for payload in (missing_sphere_payload, empty_sphere_payload):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError) as context:
                    Spell.model_validate(payload)

                self.assertIn("must have at least one sphere", str(context.exception))

    def test_unknown_school_and_sphere_mark_review_and_append_notes(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.PRIEST
        payload["level"] = 4
        payload["school"] = ["Runecraft"]
        payload["sphere"] = ["Starlight"]
        payload["review_notes"] = "Needs source verification."

        spell = Spell.model_validate(payload)

        self.assertTrue(spell.needs_review)
        self.assertIsNotNone(spell.review_notes)
        self.assertIn("Needs source verification.", spell.review_notes)
        self.assertIn("Unknown school(s): Runecraft.", spell.review_notes)
        self.assertIn("Unknown sphere(s): Starlight.", spell.review_notes)

    def test_custom_school_and_sphere_context_do_not_mark_review(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.PRIEST
        payload["level"] = 4
        payload["school"] = ["Runecraft"]
        payload["sphere"] = ["Starlight"]
        payload["review_notes"] = "Initial review note."

        spell = Spell.model_validate(
            payload,
            context={"custom_schools": ["Runecraft"], "custom_spheres": ["Starlight"]},
        )

        self.assertFalse(spell.needs_review)
        self.assertEqual(spell.review_notes, "Initial review note.")

    def test_wizard_spell_rejects_non_null_sphere(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.WIZARD
        payload["level"] = 3
        payload["sphere"] = ["All"]

        with self.assertRaises(ValidationError) as context:
            Spell.model_validate(payload)

        self.assertIn("Wizard spells must not have a sphere", str(context.exception))

    def test_unknown_school_appends_note_when_existing_note_is_none_or_empty(self) -> None:
        expected = "Unknown school(s): Runecraft."
        for existing_note in (None, ""):
            with self.subTest(existing_note=existing_note):
                payload = _base_spell_payload()
                payload["class_list"] = ClassList.WIZARD
                payload["level"] = 2
                payload["school"] = ["Runecraft"]
                payload["review_notes"] = existing_note

                spell = Spell.model_validate(payload)

                self.assertTrue(spell.needs_review)
                self.assertEqual(spell.review_notes, expected)

    def test_unknown_school_appends_with_semicolon_when_note_has_no_terminal_punctuation(self) -> None:
        payload = _base_spell_payload()
        payload["class_list"] = ClassList.WIZARD
        payload["level"] = 2
        payload["school"] = ["Runecraft"]
        payload["review_notes"] = "Needs source verification"

        spell = Spell.model_validate(payload)

        self.assertTrue(spell.needs_review)
        self.assertEqual(
            spell.review_notes,
            "Needs source verification; Unknown school(s): Runecraft.",
        )

    def test_school_is_required_for_all_spells(self) -> None:
        payload = _base_spell_payload()
        payload["school"] = []

        with self.assertRaises(ValidationError) as context:
            Spell.model_validate(payload)

        self.assertIn("must have at least one school", str(context.exception))

    def test_lax_spell_to_spell_uses_canonical_conversion_when_payload_is_valid(self) -> None:
        lax_spell = LaxSpell(
            name="Healing Light",
            class_list="Priest",
            level="3",
            school=["Abjuration"],
            sphere=["Healing"],
            range="Touch",
            components=["V", "S"],
            duration="1 turn",
            casting_time="5",
            area_of_effect="1 creature",
            saving_throw="None",
            description="A stabilizing prayer.",
            source_document="sample-source.pdf",
            confidence=0.73,
        )

        spell = lax_spell.to_spell()

        self.assertEqual(spell.class_list, ClassList.PRIEST)
        self.assertEqual(spell.level, 3)
        self.assertEqual(spell.sphere, ["Healing"])
        self.assertEqual([component.value for component in spell.components], ["V", "S"])
        self.assertAlmostEqual(spell.confidence, 0.73)
        self.assertFalse(spell.needs_review)
        self.assertIsNone(spell.review_notes)

    def test_lax_spell_to_spell_fallback_sets_review_flags_for_invalid_input(self) -> None:
        lax_spell = LaxSpell(
            name="Broken Prayer",
            class_list="Priest",
            level="9",
            school=["Runecraft"],
            sphere=[],
            range="30 yards",
            components=["V", "X"],
            duration="1 round",
            casting_time="1",
            area_of_effect="1 creature",
            saving_throw="None",
            description="A malformed extraction payload.",
            source_document="sample-source.pdf",
            review_notes="Initial extractor warning.",
        )

        spell = lax_spell.to_spell()

        self.assertTrue(spell.needs_review)
        self.assertIsNotNone(spell.review_notes)
        assert spell.review_notes is not None
        self.assertIn("Initial extractor warning.", spell.review_notes)
        self.assertIn("Validation errors:", spell.review_notes)
        self.assertIn("Class fell back to Wizard", spell.review_notes)
        self.assertEqual(spell.confidence, 0.0)
        self.assertEqual(spell.class_list, ClassList.WIZARD)

    def test_lax_spell_fallback_handles_non_finite_numeric_metadata(self) -> None:
        lax_spell = LaxSpell.model_construct(
            name="Broken Spell",
            class_list="Wizard",
            level="not-a-level",
            school=["Evocation"],
            range="30 yards",
            components=["V", "S"],
            duration="1 round",
            casting_time="1",
            area_of_effect="1 creature",
            saving_throw="None",
            description="A broken payload for fallback testing.",
            source_document="sample-source.pdf",
            source_page=math.inf,
            extraction_start_line=math.nan,
            extraction_end_line=-math.inf,
        )

        spell = lax_spell.to_spell()

        self.assertTrue(spell.needs_review)
        self.assertEqual(spell.level, 0)
        self.assertIsNone(spell.source_page)
        self.assertEqual(spell.extraction_start_line, -1)
        self.assertEqual(spell.extraction_end_line, -1)


if __name__ == "__main__":
    unittest.main()