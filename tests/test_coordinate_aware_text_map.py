from __future__ import annotations

import math
import unittest

from pydantic import ValidationError

from app.models import CoordinateAwareTextMap, TextRegion


class TextRegionModelTests(unittest.TestCase):
    def test_pdf_text_region_round_trips_with_json_payload(self) -> None:
        region = TextRegion(
            page=2,
            bbox=(15.0, 30.5, 200.25, 44.75),
        )

        payload = region.model_dump(mode="json")
        restored = TextRegion.model_validate(payload)

        self.assertEqual(restored.model_dump(mode="json"), payload)

    def test_docx_text_region_round_trips_with_json_payload(self) -> None:
        region = TextRegion(
            page=-1,
            char_offset=(10, 26),
        )

        payload = region.model_dump(mode="json")
        restored = TextRegion.model_validate(payload)

        self.assertEqual(restored.model_dump(mode="json"), payload)

    def test_text_region_rejects_invalid_coordinate_combinations(self) -> None:
        invalid_regions = [
            {"page": 1},
            {"page": -1, "bbox": (1.0, 2.0, 3.0, 4.0)},
            {"page": 0, "char_offset": (1, 2)},
            {"page": 1, "bbox": (1.0, 2.0, 3.0, 4.0), "char_offset": (5, 8)},
            {"page": -1, "char_offset": (8, 3)},
            {"page": -1, "char_offset": (-1, 3)},
            {"page": 2, "bbox": (8.0, 2.0, 7.0, 4.0)},
        ]

        for payload in invalid_regions:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TextRegion(**payload)

    def test_text_region_rejects_non_finite_bbox_values(self) -> None:
        invalid_regions = [
            {"page": 1, "bbox": (math.nan, 2.0, 3.0, 4.0)},
            {"page": 1, "bbox": (1.0, math.inf, 3.0, 4.0)},
            {"page": 1, "bbox": (1.0, 2.0, -math.inf, 4.0)},
        ]

        for payload in invalid_regions:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TextRegion(**payload)


class CoordinateAwareTextMapModelTests(unittest.TestCase):
    def test_coordinate_map_round_trips_with_json_payload(self) -> None:
        text_map = CoordinateAwareTextMap(
            lines=[
                ("Name", TextRegion(page=0, bbox=(4.0, 8.0, 44.0, 18.0))),
                ("Level", TextRegion(page=0, bbox=(6.0, 20.0, 56.0, 30.0))),
                ("Range", TextRegion(page=1, bbox=(8.0, 32.0, 68.0, 42.0))),
            ],
        )

        payload = text_map.model_dump(mode="json")
        restored = CoordinateAwareTextMap.model_validate(payload)

        self.assertEqual(restored.model_dump(mode="json"), payload)

    def test_coordinate_map_safe_lookup_helpers(self) -> None:
        pdf_region = TextRegion(page=0, bbox=(1.0, 2.0, 3.0, 4.0))
        docx_region = TextRegion(page=-1, char_offset=(12, 18))
        text_map = CoordinateAwareTextMap(
            lines=[("A", pdf_region), ("B", docx_region)],
        )

        self.assertEqual(text_map.get_line(0), "A")
        self.assertEqual(text_map.get_line(1), "B")
        self.assertIsNone(text_map.get_line(5))
        self.assertIsNone(text_map.get_line(-1))

        self.assertEqual(text_map.get_region(0), pdf_region)
        self.assertEqual(text_map.get_region(1), docx_region)
        self.assertIsNone(text_map.get_region(5))
        self.assertIsNone(text_map.get_region(-1))

    def test_coordinate_map_regions_for_range(self) -> None:
        first = TextRegion(page=0, bbox=(1.0, 2.0, 3.0, 4.0))
        second = TextRegion(page=1, bbox=(5.0, 6.0, 7.0, 8.0))
        third = TextRegion(page=-1, char_offset=(100, 120))
        text_map = CoordinateAwareTextMap(
            lines=[
                ("A", first),
                ("B", second),
                ("C", third),
            ]
        )

        self.assertEqual(text_map.regions_for_range(0, 2), [first, second])
        self.assertEqual(text_map.regions_for_range(1, 3), [second, third])

    def test_coordinate_map_page_span(self) -> None:
        text_map = CoordinateAwareTextMap(
            lines=[
                ("A", TextRegion(page=0, bbox=(1.0, 2.0, 3.0, 4.0))),
                ("B", TextRegion(page=3, bbox=(5.0, 6.0, 7.0, 8.0))),
                ("C", TextRegion(page=5, bbox=(9.0, 10.0, 11.0, 12.0))),
                ("D", TextRegion(page=-1, char_offset=(8, 14))),
            ]
        )

        self.assertEqual(text_map.page_span(0, 3), (0, 5))
        self.assertEqual(text_map.page_span(3, 4), (-1, -1))

    def test_coordinate_map_range_helpers_handle_invalid_ranges(self) -> None:
        text_map = CoordinateAwareTextMap(
            lines=[
                ("A", TextRegion(page=0, bbox=(1.0, 2.0, 3.0, 4.0))),
                ("B", TextRegion(page=1, bbox=(5.0, 6.0, 7.0, 8.0))),
            ]
        )

        invalid_ranges = [(-1, 1), (1, 1), (4, 5)]

        for start_line, end_line in invalid_ranges:
            with self.subTest(start_line=start_line, end_line=end_line):
                with self.assertRaises(ValueError):
                    text_map.regions_for_range(start_line, end_line)

            with self.subTest(start_line=start_line, end_line=end_line):
                with self.assertRaises(ValueError):
                    text_map.page_span(start_line, end_line)

    def test_coordinate_map_rejects_missing_region_links(self) -> None:
        with self.assertRaises(ValidationError):
            CoordinateAwareTextMap(
                lines=[("A", None)],
            )


if __name__ == "__main__":
    unittest.main()
