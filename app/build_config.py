from __future__ import annotations

import os
from typing import Literal

BuildFlavor = Literal["standard", "pro"]

_RAW_BUILD_FLAVOR = os.environ.get("SPELLSCRIBE_BUILD_FLAVOR", "standard")
_NORMALIZED_BUILD_FLAVOR = _RAW_BUILD_FLAVOR.strip().lower()
if _NORMALIZED_BUILD_FLAVOR not in {"standard", "pro"}:
    _NORMALIZED_BUILD_FLAVOR = "standard"

BUILD_FLAVOR: BuildFlavor = _NORMALIZED_BUILD_FLAVOR  # type: ignore[assignment]


def is_pro_build() -> bool:
    return BUILD_FLAVOR == "pro"


def edition_label() -> str:
    if is_pro_build():
        return "Pro Edition"
    return "Standard Edition"
