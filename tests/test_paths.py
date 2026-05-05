from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.paths import resolve_tessdata_prefix, resolve_tesseract_executable


class PathResolutionTests(unittest.TestCase):
    def test_resolve_tesseract_executable_prefers_configured_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            configured_exe = Path(tmp_dir) / "tesseract.exe"
            configured_exe.write_text("", encoding="utf-8")

            resolved = resolve_tesseract_executable(f" {configured_exe} ")
            self.assertEqual(resolved, str(configured_exe))

    def test_resolve_tesseract_executable_falls_back_to_bundled_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundled_dir = Path(tmp_dir) / "vendor" / "tesseract"
            bundled_dir.mkdir(parents=True, exist_ok=True)
            bundled_exe = bundled_dir / "tesseract.exe"
            bundled_exe.write_text("", encoding="utf-8")

            with patch("app.paths.frozen_bundle_dir", return_value=Path(tmp_dir)):
                resolved = resolve_tesseract_executable("")
            self.assertEqual(resolved, str(bundled_exe))

    def test_resolve_tesseract_executable_ignores_missing_configured_path_and_uses_bundle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundled_dir = Path(tmp_dir) / "vendor" / "tesseract"
            bundled_dir.mkdir(parents=True, exist_ok=True)
            bundled_exe = bundled_dir / "tesseract.exe"
            bundled_exe.write_text("", encoding="utf-8")

            missing_configured_path = Path(tmp_dir) / "does-not-exist.exe"
            with patch("app.paths.frozen_bundle_dir", return_value=Path(tmp_dir)):
                resolved = resolve_tesseract_executable(str(missing_configured_path))
            self.assertEqual(resolved, str(bundled_exe))

    def test_resolve_tessdata_prefix_detects_neighbor_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            exe = Path(tmp_dir) / "tesseract.exe"
            exe.write_text("", encoding="utf-8")
            tessdata = Path(tmp_dir) / "tessdata"
            tessdata.mkdir(parents=True, exist_ok=True)

            resolved = resolve_tessdata_prefix(str(exe))
            self.assertEqual(resolved, str(tessdata))

    def test_resolve_tessdata_prefix_detects_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            install_dir = Path(tmp_dir) / "Tesseract-OCR"
            bin_dir = install_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            exe = bin_dir / "tesseract.exe"
            exe.write_text("", encoding="utf-8")
            tessdata = install_dir / "tessdata"
            tessdata.mkdir(parents=True, exist_ok=True)

            resolved = resolve_tessdata_prefix(str(exe))
            self.assertEqual(resolved, str(tessdata))
