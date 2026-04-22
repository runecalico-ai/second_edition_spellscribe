## Sequencing

- Implement after `add-core-session-models`.
- Finish this before `add-discovery-and-pending-queue` and `add-desktop-shell-and-settings` so document metadata resolution and coordinate maps already exist.

## 1. Document identity and metadata

- [x] 1.1 Add SHA-256 hashing helpers and metadata lookup for document name, page offset, and force-OCR state
- [x] 1.2 Implement the document-identity metadata resolver that the desktop shell will call for unknown document hashes

## 2. Ingestion routing and coordinate maps

- [x] 2.1 Implement `route_document()` for PDF and DOCX branches in `app/pipeline/ingestion.py`
- [x] 2.2 Implement scanned-page detection and OCR routing in `app/pipeline/detector.py`
- [x] 2.3 Populate `CoordinateAwareTextMap` output for digital PDF, OCR PDF, and DOCX inputs

## 3. Verification

- [x] 3.1 Add unit tests for scanned detection, force-OCR overrides, and document-offset defaults
- [x] 3.2 Add fixture-based tests for PDF and DOCX coordinate-map generation
