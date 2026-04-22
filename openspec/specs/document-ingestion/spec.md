# Capability: document-ingestion

## Purpose
Normalize imported PDF and DOCX documents into markdown, source coordinates, and document identity defaults for later discovery, extraction, review, and export workflows.

## Requirements

### Requirement: Route documents by input type
The system SHALL accept PDF and DOCX inputs and route each file through the correct ingestion path.

#### Scenario: PDF uses PDF ingestion path
- **WHEN** the user opens a `.pdf` file
- **THEN** the system routes the file through the PDF ingestion branch

#### Scenario: DOCX uses DOCX ingestion path
- **WHEN** the user opens a `.docx` file
- **THEN** the system routes the file through the DOCX ingestion branch

### Requirement: Detect scanned PDF pages and honor force-OCR overrides
The system SHALL detect scanned PDF pages with the text-ratio rule and SHALL override that decision when `force_ocr_by_sha256` is set for the source file.

#### Scenario: Low text ratio marks page as scanned
- **WHEN** a PDF page has `text_ratio < 0.005`
- **THEN** the system treats that page as scanned

#### Scenario: Force OCR overrides digital-text detection
- **WHEN** `force_ocr_by_sha256[source_sha]` is true for the opened PDF
- **THEN** the system routes the PDF through the OCR ingestion branch even if the text ratio suggests digital text

### Requirement: Every ingestion path produces coordinate-aware output
The system SHALL return a `CoordinateAwareTextMap` for every supported ingestion path.

#### Scenario: Digital PDF returns bounding boxes
- **WHEN** the system ingests a digital PDF page
- **THEN** the returned line map includes PDF page numbers and bounding boxes for mapped lines

#### Scenario: DOCX returns character offsets
- **WHEN** the system ingests a DOCX file
- **THEN** the returned line map includes character offsets and no PDF bounding boxes

### Requirement: Unknown documents require identity metadata
The system SHALL collect source-document metadata for unknown document hashes before later pipeline stages use that file.

#### Scenario: Unknown SHA prompts for document identity
- **WHEN** the user opens a document whose SHA-256 has no stored metadata
- **THEN** the app asks for source document display name and page offset defaults before continuing

#### Scenario: Known SHA reuses stored metadata
- **WHEN** the user opens a document whose SHA-256 already has stored metadata
- **THEN** the app reuses the stored document name, page offset, and force-OCR settings

### Requirement: Source page defaults follow file-type rules
The system SHALL derive default `source_page` values according to the revised spec.

#### Scenario: PDF source pages use stored offset
- **WHEN** the system creates spell records from a PDF
- **THEN** the default `source_page` value uses the stored PDF-to-book page offset

#### Scenario: DOCX without stable page sequence leaves source page empty
- **WHEN** a DOCX conversion does not produce a non-empty and internally consistent page sequence
- **THEN** the system leaves `source_page` unset until the user fills it later