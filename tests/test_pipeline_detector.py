from __future__ import annotations

import unittest

from app.pipeline.detector import (
    SCANNED_TEXT_RATIO_THRESHOLD,
    is_scanned_page,
    should_route_pdf_to_ocr,
)


class ScannedDetectionTests(unittest.TestCase):
    def test_ratio_below_threshold_is_scanned(self) -> None:
        self.assertTrue(is_scanned_page(SCANNED_TEXT_RATIO_THRESHOLD - 0.0001))

    def test_ratio_equal_or_above_threshold_is_not_scanned(self) -> None:
        self.assertFalse(is_scanned_page(SCANNED_TEXT_RATIO_THRESHOLD))
        self.assertFalse(is_scanned_page(SCANNED_TEXT_RATIO_THRESHOLD + 0.001))

    def test_force_ocr_override_routes_pdf_to_ocr(self) -> None:
        self.assertTrue(should_route_pdf_to_ocr([0.8, 0.9], force_ocr=True))

    def test_scanned_page_routes_pdf_to_ocr_without_force_override(self) -> None:
        self.assertTrue(should_route_pdf_to_ocr([0.8, 0.004], force_ocr=False))

    def test_digital_pages_without_override_stay_on_digital_path(self) -> None:
        self.assertFalse(should_route_pdf_to_ocr([0.2, 0.3], force_ocr=False))


if __name__ == "__main__":
    unittest.main()
