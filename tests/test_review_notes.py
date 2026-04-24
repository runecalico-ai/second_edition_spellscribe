from __future__ import annotations

import unittest

from app.utils.review_notes import parse_alt_tags, strip_alt_tags, upsert_alt_tag


class ReviewNotesHelperTests(unittest.TestCase):
    def test_parse_alt_tags_returns_last_value_per_field(self) -> None:
        notes = "Needs review. ALT[level]=2 ALT[level]=3 ALT[range]=Touch"

        parsed = parse_alt_tags(notes)

        self.assertEqual(parsed, {"level": "3", "range": "Touch"})

    def test_upsert_alt_tag_replaces_existing_tag(self) -> None:
        notes = "Manual text ALT[level]=1 ALT[range]=10 yards"

        updated = upsert_alt_tag(notes, "level", "2")

        self.assertEqual(
            updated,
            "Manual text ALT[level]=2 ALT[range]=10 yards",
        )

    def test_strip_alt_tags_removes_all_alt_fragments(self) -> None:
        notes = "Manual value kept. ALT[level]=2 ALT[school]=[\"Evocation\"]"

        stripped = strip_alt_tags(notes)

        self.assertEqual(stripped, "Manual value kept.")

    def test_multiline_alt_value_round_trips_without_corrupting_notes_h001(self) -> None:
        """H-001: multiline ALT values must not truncate parse or leave tail in free text."""
        notes = upsert_alt_tag("Manual note.", "description", "Line 1\nLine 2")

        self.assertEqual(parse_alt_tags(notes)["description"], "Line 1\nLine 2")
        self.assertEqual(strip_alt_tags(notes), "Manual note.")


if __name__ == "__main__":
    unittest.main()

