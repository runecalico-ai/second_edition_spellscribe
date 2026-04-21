from __future__ import annotations

import os
from pathlib import Path


_APP_SUBDIR = "SpellScribe"


def spellscribe_data_dir() -> Path:
    """Return the SpellScribe application data directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata)
    else:
        base_dir = Path.home() / "AppData" / "Roaming"
    return base_dir / _APP_SUBDIR