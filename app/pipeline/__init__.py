from __future__ import annotations

from app.pipeline.detector import (
    SCANNED_TEXT_RATIO_THRESHOLD,
    is_scanned_page,
    should_route_pdf_to_ocr,
)
from app.pipeline.identity import (
    DocumentIdentityInput,
    DocumentIdentityMetadata,
    UnknownDocumentIdentityError,
    compute_sha256_hex,
    lookup_document_identity,
    resolve_document_identity,
)
from app.pipeline.ingestion import (
    DOCXIngestionPayload,
    DOCXLineFragment,
    PDFIngestionPayload,
    PDFLineFragment,
    RoutedDocument,
    build_docx_coordinate_map,
    build_pdf_coordinate_map,
    route_document,
)

__all__ = [
    "SCANNED_TEXT_RATIO_THRESHOLD",
    "DOCXIngestionPayload",
    "DOCXLineFragment",
    "DocumentIdentityInput",
    "DocumentIdentityMetadata",
    "PDFIngestionPayload",
    "PDFLineFragment",
    "RoutedDocument",
    "UnknownDocumentIdentityError",
    "build_docx_coordinate_map",
    "build_pdf_coordinate_map",
    "compute_sha256_hex",
    "is_scanned_page",
    "lookup_document_identity",
    "resolve_document_identity",
    "route_document",
    "should_route_pdf_to_ocr",
]
