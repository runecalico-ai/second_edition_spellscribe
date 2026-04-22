from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.config import AppConfig


class UnknownDocumentIdentityError(RuntimeError):
    def __init__(self, source_sha256_hex: str):
        super().__init__(
            "Document identity metadata is required before ingestion can continue "
            f"for SHA-256 {source_sha256_hex}."
        )
        self.source_sha256_hex = source_sha256_hex


@dataclass(frozen=True)
class DocumentIdentityMetadata:
    source_sha256_hex: str
    source_display_name: str
    page_offset: int
    force_ocr: bool


@dataclass(frozen=True)
class DocumentIdentityInput:
    source_display_name: str
    page_offset: int = 0
    force_ocr: bool = False


class UnknownDocumentIdentityResolver(Protocol):
    def __call__(self, source_sha256_hex: str) -> DocumentIdentityInput:
        ...


_MISSING = object()


def compute_sha256_hex(
    source_path: str | Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    digest = hashlib.sha256()
    path = Path(source_path)

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def lookup_document_identity(
    config: AppConfig,
    source_sha256_hex: str,
) -> DocumentIdentityMetadata | None:
    digest = source_sha256_hex.strip().lower()
    source_name = config.document_names_by_sha256.get(digest)
    if source_name is None:
        return None

    return DocumentIdentityMetadata(
        source_sha256_hex=digest,
        source_display_name=source_name,
        page_offset=config.document_offsets.get(digest, 0),
        force_ocr=config.force_ocr_by_sha256.get(digest, False),
    )


def resolve_document_identity(
    config: AppConfig,
    source_sha256_hex: str,
    *,
    resolver: UnknownDocumentIdentityResolver | None = None,
) -> DocumentIdentityMetadata:
    digest = source_sha256_hex.strip().lower()
    existing = lookup_document_identity(config, digest)
    if existing is not None:
        return existing

    if resolver is None:
        raise UnknownDocumentIdentityError(digest)

    provided = resolver(digest)
    source_display_name = _coerce_source_display_name(
        _read_resolver_payload_field(provided, "source_display_name"),
        digest,
        default_source_document=config.default_source_document,
    )
    page_offset = _coerce_page_offset(
        _read_resolver_payload_field(provided, "page_offset"),
        digest,
    )
    force_ocr = _coerce_force_ocr(
        _read_resolver_payload_field(provided, "force_ocr"),
        digest,
    )

    metadata = DocumentIdentityMetadata(
        source_sha256_hex=digest,
        source_display_name=source_display_name,
        page_offset=page_offset,
        force_ocr=force_ocr,
    )

    config.document_names_by_sha256[digest] = metadata.source_display_name
    config.document_offsets[digest] = metadata.page_offset
    config.force_ocr_by_sha256[digest] = metadata.force_ocr

    return metadata


def _read_resolver_payload_field(payload: Any, field_name: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(field_name, _MISSING)
    return getattr(payload, field_name, _MISSING)


def _coerce_source_display_name(
    raw_value: Any,
    source_sha256_hex: str,
    *,
    default_source_document: str,
) -> str:
    if raw_value is _MISSING or not isinstance(raw_value, str):
        raise UnknownDocumentIdentityError(source_sha256_hex)

    normalized = raw_value.strip()
    if not normalized:
        return default_source_document
    return normalized


def _coerce_page_offset(raw_value: Any, source_sha256_hex: str) -> int:
    if raw_value is _MISSING:
        return 0

    parsed = _parse_strict_int(raw_value)
    if parsed is None:
        raise UnknownDocumentIdentityError(source_sha256_hex)
    return parsed


def _coerce_force_ocr(raw_value: Any, source_sha256_hex: str) -> bool:
    if raw_value is _MISSING:
        return False

    parsed = _parse_optional_bool(raw_value)
    if parsed is None:
        raise UnknownDocumentIdentityError(source_sha256_hex)
    return parsed


def _parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None

    if isinstance(value, int):
        if value == 0:
            return False
        if value == 1:
            return True

    return None


def _parse_strict_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None

        sign = stripped[0] in {"+", "-"}
        digits = stripped[1:] if sign else stripped
        if not digits.isdigit():
            return None

        try:
            return int(stripped)
        except ValueError:
            return None

    return None
