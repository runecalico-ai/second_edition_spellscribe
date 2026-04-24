# AGENTS.md

This file provides guidance to Agents when working with code in this repository.

## Project Overview

**SpellScribe** is a Windows desktop application that extracts AD&D 2nd Edition spell descriptions from scanned PDFs and Word documents using a two-stage Claude API pipeline:
- **Stage 1** (Boundary Detection): Claude Haiku identifies spell boundaries across document pages
- **Stage 2** (Spell Extraction): Claude Sonnet with Instructor extracts structured spell data into validated Pydantic schemas

Uncertain extractions are queued for human review in the UI before export as JSON or Markdown.

## Commands

```pwsh
# Activate virtual environment (Windows)
. .\.venv\Scripts\Activate.ps1
# Run all tests
python -m unittest discover tests/

# Run a single test file
python -m unittest tests/test_spell_models.py

# Run a single test case
python -m unittest tests.test_spell_models.TestSpellValidation.test_wizard_level_valid

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Pipeline Flow

```
Document (PDF/DOCX)
  → pipeline/detector.py    # Detect scanned vs. digital PDF
  → pipeline/ingestion.py   # Convert to Markdown + CoordinateAwareTextMap
  → [Stage 1 LLM]           # Boundary detection (not yet implemented)
  → [Stage 2 LLM]           # Spell extraction into LaxSpell (not yet implemented)
  → LaxSpell.to_spell()     # Coerce to strict Spell with validation
  → SessionState            # Track records in three-state workflow
  → [UI review]             # Human review of uncertain extractions (not yet implemented)
  → Export (JSON/Markdown)  # (not yet implemented)
```

### Key Modules

- **`app/models.py`** — Core schemas: `Spell` (strict), `LaxSpell` (lenient extraction target), `TextRegion`, `CoordinateAwareTextMap`. `Spell.model_validate()` accepts `custom_schools`/`custom_spheres` as validation context for user-learned values.
- **`app/config.py`** — `AppConfig` dataclass; persists to `%APPDATA%\SpellScribe\config.json`. API key can come from env var, Windows Credential Manager (`keyring`), or plaintext. Keyed config fields (document names, offsets, OCR overrides) use SHA-256 as key.
- **`app/session.py`** — `SessionState` + `SpellRecord` with three-state workflow: `pending_extraction → needs_review → confirmed`. Persists to `%APPDATA%\SpellScribe\session.json`.
- **`app/paths.py`** — Windows `%APPDATA%\SpellScribe` directory resolution.
- **`app/pipeline/ingestion.py`** — Routes documents to PDF/DOCX handlers; returns `RoutedDocument` with Markdown + coordinate map. OCR fallback via `pytesseract`.
- **`app/pipeline/detector.py`** — Heuristic scanned PDF detection (`text_ratio < 0.005`).
- **`app/pipeline/identity.py`** — SHA-256 file hashing for content-addressed session/config storage.

### Data Model Highlights

**`Spell`** (strict): `name`, `class_list` (Wizard/Priest), `level` (Wizard 0–9 where 0=Cantrip; Priest 1–8 where 8=Quest), `schools` (≥1), `spheres` (≥1 for Priest, None for Wizard), stat block fields, `confidence` (0.0–1.0), `needs_review`, `extraction_start_line`/`end_line`.

**`CoordinateAwareTextMap`**: Maps each Markdown line to its source location — PDF bounding box `(x0, y0, x1, y1)` or DOCX character offsets. Enables UI highlighting and page-spanning navigation.

**`SpellRecord`**: Immutable `spell_id`, mutable section order, optional `canonical_spell` (committed) + optional `draft_spell` (in-progress edits).

### Storage Patterns

- Config and session use atomic temp-file-then-replace writes for durability.
- Corrupt files are quarantined to `.bad.<UTC-timestamp>` rather than deleted.
- Session identity is content-addressed by SHA-256, surviving file moves/renames.

### Implementation Status

**Done:** Core models, `AppConfig`, `SessionState`, document ingestion pipeline, coordinate mapping, test suite with fixtures.

**Not yet implemented:** UI (PySide6), LLM extraction stages (boundary detection + Instructor-based extraction), export (JSON/Markdown), settings dialog, PyInstaller packaging.

## Tech Stack

- **Python 3.12** for all code, use Virtual Environments (`venv`) for dependency management
- **Pydantic v2** for all schemas and validation
- **pymupdf / pymupdf4llm** for PDF text extraction and Markdown conversion
- **docx2python / python-docx** for DOCX processing
- **pytesseract** for OCR fallback on scanned PDFs
- **PySide6** for the desktop UI (not yet implemented)
- **Instructor** for structured LLM output (not yet implemented)
- **keyring** for Windows Credential Manager API key storage

## Windows-Specific Notes

- All runtime paths resolve under `%APPDATA%\SpellScribe`.
- Tesseract is expected to be bundled in the PyInstaller distribution; path configurable in `AppConfig.tesseract_path`.
- See `docs/windows-tesseract-setup.md` for local dev Tesseract installation.
