from __future__ import annotations

from collections.abc import Sequence

SCANNED_TEXT_RATIO_THRESHOLD = 0.005


def is_scanned_page(text_ratio: float) -> bool:
    return text_ratio < SCANNED_TEXT_RATIO_THRESHOLD


def should_route_pdf_to_ocr(
    text_ratios: Sequence[float],
    *,
    force_ocr: bool,
) -> bool:
    if force_ocr:
        return True

    for raw_ratio in text_ratios:
        try:
            ratio = float(raw_ratio)
        except (TypeError, ValueError):
            continue
        if is_scanned_page(ratio):
            return True

    return False
