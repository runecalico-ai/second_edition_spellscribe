## Context

The revised spec requires one ingestion entry point that can normalize PDF and DOCX inputs into markdown plus source coordinates. This change sits between the core models and the later discovery and extraction pipeline.

The implementation must support:
- digital PDF ingestion through PyMuPDF and PyMuPDF4LLM
- scanned PDF ingestion through Marker or Tesseract
- DOCX ingestion through docx2python
- SHA-keyed document metadata for source names, offsets, and force-OCR behavior

The actual desktop dialog for unknown document hashes belongs to the workbench change. This change defines the metadata contract and resolver that dialog will use.

## Goals / Non-Goals

**Goals:**
- Implement document hashing and metadata lookup keyed by SHA-256.
- Implement file routing for PDF and DOCX sources.
- Produce `CoordinateAwareTextMap` output for every ingestion path.
- Define the document-identity prompt and metadata persistence rules.
- Preserve PDF and DOCX `source_page` default behavior from the spec.

**Non-Goals:**
- Implement Stage 1 spell discovery.
- Implement Stage 2 extraction.
- Implement review editing or export.
- Implement packaging.

## Decisions

### Route all imports through one `route_document()` entry point
- One public entry point keeps later discovery code independent of the original file type.
- Per-format helpers stay separate under the pipeline module.

Alternative considered:
- Expose separate import functions to callers.
- Rejected because later UI and worker code would need format-specific branching.

### Use SHA-256 as the document identity key
- SHA-256 stays stable across rename and move operations.
- The same key supports page offsets, force-OCR overrides, and session restore.

Alternative considered:
- Use display name or file path as the primary key.
- Rejected because both are unstable and can collide.

### Keep source coordinates in the ingestion output, not in a later enrichment pass
- Digital PDF, Marker, Tesseract, and DOCX paths already know the source coordinates when they generate text.
- Saving coordinates immediately avoids a second reconciliation pass.

Alternative considered:
- Build raw markdown first and recover coordinates later.
- Rejected because OCR output and PDF block layout are easier to match during the initial pass.

### Capture document identity before first-use ingestion for unknown SHA values
- The metadata resolver provides a correct source name and page offset before spell records are created.
- Later changes can trust the stored metadata instead of backfilling it across extracted records.

Alternative considered:
- Ask for metadata only during extraction or review.
- Rejected because it delays document-wide defaults until after records already exist.

## Risks / Trade-offs

- OCR output quality can vary by page and engine → Keep the routing logic explicit and preserve force-OCR by SHA.
- Coordinate mapping across multiple ingestion libraries can drift → Write focused tests for line-count and coordinate-shape correctness.
- DOCX page numbers can be unavailable or inconsistent → Leave `source_page` empty in that case and let later review flow fill it.

## Migration Plan

- This is greenfield work with no shipped imports to migrate.
- Preserve the documented legacy offset remapping hook in `AppConfig` for future compatibility.

## Open Questions

- None for this change.
