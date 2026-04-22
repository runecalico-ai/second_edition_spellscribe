# Windows Tesseract Setup

This note explains how to set up Tesseract for local SpellScribe runs on Windows.

## Local Install

1. Download the Windows installer from the UB Mannheim Tesseract build.
2. Install Tesseract to `C:\Program Files\Tesseract-OCR`.
3. Keep the English language data during the install.
4. Make sure `C:\Program Files\Tesseract-OCR\tesseract.exe` exists after the install.

## App Wiring

Use one of these options:

1. Add `C:\Program Files\Tesseract-OCR` to `PATH`.
2. Set `AppConfig.tesseract_path` to `C:/Program Files/Tesseract-OCR/tesseract.exe`.

When `tesseract_path` is set, SpellScribe uses that value in `app/pipeline/ingestion.py` before it calls `pytesseract.image_to_data()`.

## Quick Check

1. Open PowerShell.
2. Run `tesseract --version`.
3. If the command fails, fix `PATH` or set `AppConfig.tesseract_path`.

## Notes

1. This setup is for local development and local runs.
2. The current ingestion code sets `pytesseract.pytesseract.tesseract_cmd` when `tesseract_path` is present.
3. Frozen Windows bundles still need bundled-binary setup for `TESSDATA_PREFIX`.
4. That packaged-build work belongs to the `add-windows-packaging` change.