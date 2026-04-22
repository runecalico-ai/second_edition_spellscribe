## Why

SpellScribe needs deterministic document routing and document identity before discovery or extraction can produce stable results. If ingestion, coordinate mapping, and SHA-based metadata are not defined first, later pipeline and UI changes will build on inconsistent source data.

## What Changes

- Add document hashing and metadata lookup for source document name, page offset, and force-OCR decisions.
- Implement `.pdf` and `.docx` routing in `route_document()`.
- Detect scanned PDF pages with the documented text-ratio rule and honor force-OCR overrides keyed by source SHA-256.
- Produce a `CoordinateAwareTextMap` for digital PDFs, scanned PDFs, fallback OCR, and DOCX imports.
- Define the document-identity metadata contract and the resolver the desktop shell will call for unknown files.
- Define `source_page` default behavior for PDF and DOCX imports.

## Capabilities

### New Capabilities
- `document-ingestion`: Document routing, coordinate-aware source mapping, and SHA-keyed identity metadata for imported files.

### Modified Capabilities
- None.

## Impact

- Affected code: `app/pipeline/ingestion.py`, `app/pipeline/detector.py`, `app/config.py`, `app/session.py`, `tests/**`
- Affected behavior: file-open flow, OCR routing, coordinate mapping, page-offset defaults, and force-OCR metadata
- Dependencies: `PyMuPDF`, `pymupdf4llm`, `docx2python`, `marker-pdf`, `pytesseract`, `Pillow`
