# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parent
entry_script = project_root / "app" / "ui" / "main_window.py"
build_flavor_runtime_hook = (
    project_root / "app" / "runtime_hooks" / "build_flavor_standard.py"
)
if not entry_script.exists():
    raise FileNotFoundError(f"Could not locate entrypoint: {entry_script}")
if not build_flavor_runtime_hook.exists():
    raise FileNotFoundError(f"Missing runtime hook: {build_flavor_runtime_hook}")

icon_candidates = [
    project_root / "resources" / "icons" / "spellscribe.ico",
    project_root / "resources" / "icons" / "app.ico",
]
icon_path = next((candidate for candidate in icon_candidates if candidate.exists()), None)
if icon_path is None:
    raise FileNotFoundError("Could not locate icon at resources/icons/spellscribe.ico or resources/icons/app.ico")

block_cipher = None

datas = [
    (str(project_root / "resources"), "resources"),
]

_tesseract_dir = os.environ.get("SPELLSCRIBE_TESSERACT_DIR")
_normalized_tesseract_dir: Path | None = None
if _tesseract_dir:
    _normalized_tesseract_dir = Path(_tesseract_dir).expanduser().resolve(strict=False)
    datas.append((str(_normalized_tesseract_dir), "vendor/tesseract"))

_tessdata_dir = os.environ.get("SPELLSCRIBE_TESSDATA_DIR")
if _tessdata_dir:
    _normalized_tessdata_dir = Path(_tessdata_dir).expanduser().resolve(strict=False)
    _bundled_tessdata_dir = (
        _normalized_tesseract_dir / "tessdata"
        if _normalized_tesseract_dir is not None
        else None
    )
    if _normalized_tessdata_dir != _bundled_tessdata_dir:
        datas.append((str(_normalized_tessdata_dir), "vendor/tesseract/tessdata"))

hiddenimports = [
    "keyring.backends.Windows",
    "keyring.backends.null",
    "PIL._tkinter_finder",
    "pymupdf",
    "pymupdf4llm",
    "docx2python",
    "docx",
    "pytesseract",
] + collect_submodules("app.pipeline")

excludes = [
    "marker",
    "marker_pdf",
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "accelerate",
    "sentence_transformers",
    "onnxruntime",
]

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(build_flavor_runtime_hook)],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SpellScribe-Standard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SpellScribe-Standard",
)
