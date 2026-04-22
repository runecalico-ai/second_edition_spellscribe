from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Literal
from typing import Any

from app.config import AppConfig
from app.models import CoordinateAwareTextMap, TextRegion
from app.pipeline.detector import should_route_pdf_to_ocr
from app.pipeline.identity import (
    DocumentIdentityInput,
    DocumentIdentityMetadata,
    UnknownDocumentIdentityError,
    compute_sha256_hex,
    resolve_document_identity,
)


@dataclass(frozen=True)
class PDFLineFragment:
    text: str
    page: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class DOCXLineFragment:
    text: str
    char_offset: tuple[int, int]


@dataclass(frozen=True)
class PDFIngestionPayload:
    markdown_text: str
    lines: list[PDFLineFragment]


@dataclass(frozen=True)
class DOCXIngestionPayload:
    markdown_text: str
    lines: list[DOCXLineFragment]
    page_sequence: list[int] | None = None


@dataclass(frozen=True)
class RoutedDocument:
    source_path: Path
    source_sha256_hex: str
    file_type: Literal["pdf", "docx"]
    ingestion_mode: Literal["pdf_digital", "pdf_ocr", "docx"]
    markdown_text: str
    coordinate_map: CoordinateAwareTextMap
    default_source_pages: list[int | None]
    identity: DocumentIdentityMetadata


PDFTextRatioReader = Callable[[Path], Sequence[float]]
PDFIngestor = Callable[[Path], PDFIngestionPayload]
DOCXIngestor = Callable[[Path], DOCXIngestionPayload]
UnknownIdentityResolver = Callable[[str], DocumentIdentityInput]

_WHITESPACE_RE = re.compile(r"\s+")
_DOCX_LINK_RE = re.compile(r'<a href="([^"]+)">(.*?)</a>')


def _load_module(module_name: str) -> Any:
    try:
        return import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"{module_name} is required for document ingestion but is not installed."
        ) from exc


def read_pdf_text_ratios_default(source_path: Path) -> list[float]:
    fitz = _load_module("fitz")

    with fitz.open(source_path) as document:
        ratios: list[float] = []
        for page in document:
            area = float(page.rect.width * page.rect.height)
            if area <= 0:
                ratios.append(0.0)
                continue
            ratios.append(len(page.get_text("text")) / area)
    return ratios


def ingest_pdf_digital_default(source_path: Path) -> PDFIngestionPayload:
    fitz = _load_module("fitz")
    pymupdf4llm = _load_module("pymupdf4llm")

    markdown_pages: list[str] = []
    line_fragments: list[PDFLineFragment] = []

    with fitz.open(source_path) as document:
        for page_index in range(document.page_count):
            page = document[page_index]
            page_markdown = _normalize_page_markdown(
                pymupdf4llm.to_markdown(document, pages=[page_index], use_ocr=False)
            )
            page_lines = _extract_pdf_line_fragments(page_index, page)
            line_fragments.extend(page_lines)

            if page_markdown:
                markdown_pages.append(page_markdown)
            else:
                markdown_pages.append("\n".join(line.text for line in page_lines))

    return PDFIngestionPayload(
        markdown_text=_join_markdown_pages(markdown_pages),
        lines=line_fragments,
    )


def ingest_pdf_ocr_default(
    source_path: Path,
    *,
    tesseract_path: str = "",
) -> PDFIngestionPayload:
    fitz = _load_module("fitz")

    _configure_tesseract_binary(tesseract_path)

    markdown_lines: list[str] = []
    line_fragments: list[PDFLineFragment] = []
    with fitz.open(source_path) as document:
        for page_index in range(document.page_count):
            page = document[page_index]
            image = _render_pdf_page_image(page)
            page_lines = _extract_tesseract_page_lines(image, page_index)
            line_fragments.extend(page_lines)
            markdown_lines.extend(line.text for line in page_lines)

    return PDFIngestionPayload(
        markdown_text="\n".join(markdown_lines),
        lines=line_fragments,
    )


def ingest_docx_default(source_path: Path) -> DOCXIngestionPayload:
    docx2python = _load_module("docx2python").docx2python

    markdown_lines: list[str] = []
    line_fragments: list[DOCXLineFragment] = []
    cursor = 0

    with docx2python(source_path, html=True) as document:
        for paragraph in _flatten_docx_paragraphs(document.body):
            markdown_paragraph = _convert_docx_html_to_markdown(paragraph)
            for line in _split_non_empty_lines(markdown_paragraph):
                line_fragments.append(
                    DOCXLineFragment(
                        text=line,
                        char_offset=(cursor, cursor + len(line)),
                    )
                )
                markdown_lines.append(line)
                cursor += len(line) + 1

    return DOCXIngestionPayload(
        markdown_text="\n".join(markdown_lines),
        lines=line_fragments,
        page_sequence=None,
    )


def _normalize_pdf_page_index(page_value: object) -> int:
    if isinstance(page_value, bool):
        raise ValueError("PDF page index must be an integral value.")

    try:
        page_number = int(page_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("PDF page index must be an integral value.") from exc

    if not isinstance(page_value, str) and page_number != page_value:
        raise ValueError("PDF page index must be an integral value.")

    return page_number


def build_pdf_coordinate_map(lines: Sequence[PDFLineFragment]) -> CoordinateAwareTextMap:
    return CoordinateAwareTextMap(
        lines=[
            (
                line.text,
                TextRegion(
                    page=_normalize_pdf_page_index(line.page),
                    bbox=tuple(line.bbox),
                ),
            )
            for line in lines
        ]
    )


def build_docx_coordinate_map(lines: Sequence[DOCXLineFragment]) -> CoordinateAwareTextMap:
    return CoordinateAwareTextMap(
        lines=[
            (
                line.text,
                TextRegion(
                    page=-1,
                    char_offset=tuple(line.char_offset),
                ),
            )
            for line in lines
        ]
    )


def route_document(
    source_path: str | Path,
    *,
    config: AppConfig,
    resolve_unknown_identity: UnknownIdentityResolver | None = None,
    read_pdf_text_ratios: PDFTextRatioReader | None = None,
    ingest_pdf_digital: PDFIngestor | None = None,
    ingest_pdf_ocr: PDFIngestor | None = None,
    ingest_docx: DOCXIngestor | None = None,
) -> RoutedDocument:
    path = Path(source_path)
    extension = path.suffix.lower()
    if extension not in {".pdf", ".docx"}:
        raise ValueError(f"Unsupported file extension '{path.suffix}'. Expected .pdf or .docx.")

    source_sha256_hex = compute_sha256_hex(path)

    identity = resolve_document_identity(
        config,
        source_sha256_hex,
        resolver=resolve_unknown_identity,
    )

    if extension == ".pdf":
        digital_ingestor = ingest_pdf_digital or ingest_pdf_digital_default
        ocr_ingestor = ingest_pdf_ocr or (
            lambda path: ingest_pdf_ocr_default(path, tesseract_path=config.tesseract_path)
        )

        if identity.force_ocr:
            route_to_ocr = True
        else:
            ratio_reader = read_pdf_text_ratios or read_pdf_text_ratios_default
            route_to_ocr = should_route_pdf_to_ocr(
                ratio_reader(path),
                force_ocr=False,
            )

        if route_to_ocr:
            payload = ocr_ingestor(path)
            ingestion_mode: Literal["pdf_digital", "pdf_ocr", "docx"] = "pdf_ocr"
        else:
            payload = digital_ingestor(path)
            ingestion_mode = "pdf_digital"

        coordinate_map = build_pdf_coordinate_map(payload.lines)
        default_source_pages = _build_pdf_source_page_defaults(
            coordinate_map,
            identity.page_offset,
        )

        return RoutedDocument(
            source_path=path,
            source_sha256_hex=source_sha256_hex,
            file_type="pdf",
            ingestion_mode=ingestion_mode,
            markdown_text=payload.markdown_text,
            coordinate_map=coordinate_map,
            default_source_pages=default_source_pages,
            identity=identity,
        )

    if extension == ".docx":
        docx_ingestor = ingest_docx or ingest_docx_default
        payload = docx_ingestor(path)

        coordinate_map = build_docx_coordinate_map(payload.lines)
        default_source_pages = _build_docx_source_page_defaults(
            len(coordinate_map.lines),
            payload.page_sequence,
            identity.page_offset,
        )

        return RoutedDocument(
            source_path=path,
            source_sha256_hex=source_sha256_hex,
            file_type="docx",
            ingestion_mode="docx",
            markdown_text=payload.markdown_text,
            coordinate_map=coordinate_map,
            default_source_pages=default_source_pages,
            identity=identity,
        )

    raise ValueError(f"Unsupported file extension '{path.suffix}'. Expected .pdf or .docx.")


def _build_pdf_source_page_defaults(
    coordinate_map: CoordinateAwareTextMap,
    page_offset: int,
) -> list[int | None]:
    defaults: list[int | None] = []
    for _, region in coordinate_map.lines:
        defaults.append(region.page + 1 + page_offset)
    return defaults


def _build_docx_source_page_defaults(
    line_count: int,
    page_sequence: Sequence[int] | None,
    page_offset: int,
) -> list[int | None]:
    if line_count == 0:
        return []

    normalized_pages = _normalize_docx_page_sequence(page_sequence, expected_size=line_count)
    if not normalized_pages:
        return [None for _ in range(line_count)]

    return _apply_page_offset(normalized_pages, page_offset)


def _apply_page_offset(pages: Sequence[int], page_offset: int) -> list[int | None]:
    defaults: list[int | None] = []
    for page_number in pages:
        defaults.append(page_number + page_offset)
    return defaults


def _normalize_docx_page_sequence(
    page_sequence: Sequence[int] | None,
    *,
    expected_size: int,
) -> list[int]:
    if page_sequence is None:
        return []
    if len(page_sequence) != expected_size:
        return []

    normalized: list[int] = []
    last_page = 0
    for value in page_sequence:
        if isinstance(value, bool):
            return []
        try:
            page_number = int(value)
        except (TypeError, ValueError, OverflowError):
            return []

        if not isinstance(value, str) and page_number != value:
            return []

        if page_number <= 0:
            return []
        if page_number < last_page:
            return []

        normalized.append(page_number)
        last_page = page_number

    return normalized


def _extract_pdf_line_fragments(page_index: int, page: Any) -> list[PDFLineFragment]:
    raw_page = page.get_text("dict")
    line_fragments: list[PDFLineFragment] = []

    for block in raw_page.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _normalize_text_line(
                "".join(span.get("text", "") for span in line.get("spans", []))
            )
            if not text:
                continue
            bbox = _coerce_bbox(line.get("bbox"))
            if bbox is None:
                continue
            line_fragments.append(PDFLineFragment(text=text, page=page_index, bbox=bbox))

    return line_fragments


def _normalize_page_markdown(raw_markdown: str) -> str:
    lines = [line.rstrip() for line in raw_markdown.splitlines()]

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def _join_markdown_pages(markdown_pages: Sequence[str]) -> str:
    return "\n\n".join(page for page in markdown_pages if page)


def _normalize_text_line(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _coerce_bbox(raw_bbox: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return None

    try:
        return tuple(float(value) for value in raw_bbox)
    except (TypeError, ValueError):
        return None


def _flatten_docx_paragraphs(node: object) -> list[str]:
    if isinstance(node, str):
        normalized = node.strip()
        if not normalized:
            return []
        return [normalized]

    if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        paragraphs: list[str] = []
        for item in node:
            paragraphs.extend(_flatten_docx_paragraphs(item))
        return paragraphs

    return []


def _convert_docx_html_to_markdown(paragraph: str) -> str:
    markdown = html.unescape(paragraph)
    markdown = _DOCX_LINK_RE.sub(r"[\2](\1)", markdown)

    replacements = {
        "<b>": "**",
        "</b>": "**",
        "<strong>": "**",
        "</strong>": "**",
        "<i>": "*",
        "</i>": "*",
        "<em>": "*",
        "</em>": "*",
        "<u>": "",
        "</u>": "",
        "<s>": "~~",
        "</s>": "~~",
        "<sub>": "",
        "</sub>": "",
        "<sup>": "",
        "</sup>": "",
    }
    for source, target in replacements.items():
        markdown = markdown.replace(source, target)

    markdown = re.sub(r"<span[^>]*>", "", markdown)
    markdown = markdown.replace("</span>", "")
    markdown = re.sub(r"<[^>]+>", "", markdown)
    return markdown.strip()


def _split_non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _configure_tesseract_binary(tesseract_path: str) -> None:
    normalized = tesseract_path.strip()
    if not normalized:
        return

    pytesseract = _load_module("pytesseract")
    pytesseract.pytesseract.tesseract_cmd = normalized


def _render_pdf_page_image(page: Any, *, zoom: float = 2.0) -> Any:
    fitz = _load_module("fitz")
    image_module = _load_module("PIL.Image")

    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    mode = "RGB"
    if pixmap.n == 1:
        mode = "L"
    elif pixmap.n == 4:
        mode = "RGBA"

    return image_module.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)


def _extract_tesseract_page_lines(image: Any, page_index: int) -> list[PDFLineFragment]:
    ocr_data = _tesseract_image_to_data(image)
    texts = _sequence_from_mapping(ocr_data, "text")
    grouped_indices: dict[tuple[int, int, int], list[int]] = defaultdict(list)

    for index, raw_text in enumerate(texts):
        text = _normalize_text_line(str(raw_text))
        if not text:
            continue
        grouped_indices[
            (
                _coerce_int_value(_mapping_value(ocr_data, "block_num", index), index + 1),
                _coerce_int_value(_mapping_value(ocr_data, "par_num", index), 1),
                _coerce_int_value(_mapping_value(ocr_data, "line_num", index), index + 1),
            )
        ].append(index)

    line_fragments: list[PDFLineFragment] = []
    for key in sorted(grouped_indices):
        indices = grouped_indices[key]
        line_parts: list[str] = []
        lefts: list[float] = []
        tops: list[float] = []
        rights: list[float] = []
        bottoms: list[float] = []

        for index in indices:
            text = _normalize_text_line(str(_mapping_value(ocr_data, "text", index, "")))
            if not text:
                continue
            left = _coerce_float_value(_mapping_value(ocr_data, "left", index), 0.0)
            top = _coerce_float_value(_mapping_value(ocr_data, "top", index), 0.0)
            width = _coerce_float_value(_mapping_value(ocr_data, "width", index), 0.0)
            height = _coerce_float_value(_mapping_value(ocr_data, "height", index), 0.0)

            line_parts.append(text)
            lefts.append(left)
            tops.append(top)
            rights.append(left + width)
            bottoms.append(top + height)

        if not line_parts:
            continue

        line_fragments.append(
            PDFLineFragment(
                text=" ".join(line_parts),
                page=page_index,
                bbox=(min(lefts), min(tops), max(rights), max(bottoms)),
            )
        )

    return line_fragments


def _tesseract_image_to_data(image: Any) -> dict[str, list[Any]]:
    pytesseract = _load_module("pytesseract")
    return pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config="--psm 6",
    )


def _sequence_from_mapping(mapping: Mapping[str, object], key: str) -> Sequence[object]:
    raw_value = mapping.get(key, [])
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
        return raw_value
    return []


def _mapping_value(
    mapping: Mapping[str, object],
    key: str,
    index: int,
    default: object = None,
) -> object:
    values = _sequence_from_mapping(mapping, key)
    if index < 0 or index >= len(values):
        return default
    return values[index]


def _coerce_int_value(raw_value: object, default: int) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _coerce_float_value(raw_value: object, default: float) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "DOCXIngestionPayload",
    "DOCXLineFragment",
    "PDFIngestionPayload",
    "PDFLineFragment",
    "RoutedDocument",
    "UnknownDocumentIdentityError",
    "build_docx_coordinate_map",
    "build_pdf_coordinate_map",
    "ingest_docx_default",
    "ingest_pdf_digital_default",
    "ingest_pdf_ocr_default",
    "read_pdf_text_ratios_default",
    "route_document",
]
