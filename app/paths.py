from __future__ import annotations

import os
import sys
from pathlib import Path


_APP_SUBDIR = "SpellScribe"
_BUNDLED_TESSERACT_SUBDIR = Path("vendor") / "tesseract"
_TESSERACT_EXE_NAME = "tesseract.exe"


def spellscribe_data_dir() -> Path:
    """Return the SpellScribe application data directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata)
    else:
        base_dir = Path.home() / "AppData" / "Roaming"
    return base_dir / _APP_SUBDIR


def is_frozen_runtime() -> bool:
    """Return True when running from a frozen PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def frozen_bundle_dir() -> Path | None:
    """Return the active PyInstaller bundle directory when available."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not isinstance(meipass, str) or not meipass.strip():
        return None
    return Path(meipass)


def bundled_tesseract_dir() -> Path | None:
    """Return bundled Tesseract directory for frozen builds when present."""
    bundle_dir = frozen_bundle_dir()
    if bundle_dir is None:
        return None
    candidate = bundle_dir / _BUNDLED_TESSERACT_SUBDIR
    if candidate.exists():
        return candidate
    return None


def resolve_tesseract_executable(configured_path: str | Path | None) -> str:
    """Resolve Tesseract executable path from user config or frozen bundle."""
    if isinstance(configured_path, Path):
        configured_text = str(configured_path)
    elif isinstance(configured_path, str):
        configured_text = configured_path
    else:
        configured_text = ""

    normalized = configured_text.strip()
    if normalized:
        configured_executable = Path(normalized).expanduser()
        if configured_executable.is_file():
            return str(configured_executable)

    bundled_dir = bundled_tesseract_dir()
    if bundled_dir is None:
        return ""
    bundled_executable = bundled_dir / _TESSERACT_EXE_NAME
    if bundled_executable.exists():
        return str(bundled_executable)
    return ""


def resolve_tessdata_prefix(tesseract_executable: str | Path | None) -> str:
    """Resolve tessdata root from configured executable or frozen bundle."""
    search_roots: list[Path] = []

    if isinstance(tesseract_executable, str) and tesseract_executable.strip():
        executable_path = Path(tesseract_executable.strip()).expanduser()
        search_roots.append(executable_path.parent)
        search_roots.append(executable_path.parent.parent)
    elif isinstance(tesseract_executable, Path):
        search_roots.append(tesseract_executable.parent)
        search_roots.append(tesseract_executable.parent.parent)

    bundled_dir = bundled_tesseract_dir()
    if bundled_dir is not None:
        search_roots.append(bundled_dir)
        search_roots.append(bundled_dir.parent)

    seen: set[Path] = set()
    for root in search_roots:
        normalized_root = root.resolve(strict=False)
        if normalized_root in seen:
            continue
        seen.add(normalized_root)

        tessdata_dir = normalized_root / "tessdata"
        if tessdata_dir.exists():
            return str(tessdata_dir)

    return ""