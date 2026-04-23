from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import AppConfig, CREDENTIAL_ACCOUNT_NAME, CREDENTIAL_SERVICE_NAME
from app.models import CoordinateAwareTextMap
from app.pipeline.ingestion import RoutedDocument
from app.session import (
    SessionState,
    SpellRecord,
    SpellRecordStatus,
    restore_session_state_for_source,
    save_session_state,
)


_FENCED_JSON_RE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL)
_DOCX_FALLBACK_CHUNK_LINE_COUNT = 120
_STAGE1_SYSTEM_PROMPT = (
    "You are a parser for Advanced Dungeons & Dragons 2nd Edition spell books.\n"
    "Your task is to identify where each spell begins on a page, and what the current chapter/section heading is "
    '(e.g. "First-Level Spells" or "Third-Level Priest Spells").\n'
    "Return ONLY a JSON block. No prose, no markdown fences."
)


def _parse_absolute_start_line(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("start_line must not be a boolean")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("start_line must not be blank")
        if not normalized.isdigit():
            raise ValueError("start_line must contain only decimal digits")
        return int(normalized)
    return value


class DiscoverySpellStart(BaseModel):
    spell_name: str | None = None
    start_line: int = Field(ge=0)

    @field_validator("spell_name")
    @classmethod
    def _normalize_spell_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("spell_name must not be blank")
        return normalized

    @field_validator("start_line", mode="before")
    @classmethod
    def _parse_start_line(cls, value: Any) -> Any:
        return _parse_absolute_start_line(value)


class _DocumentedDiscoverySpell(BaseModel):
    spell_name: str
    start_line: int = Field(ge=0)

    @field_validator("spell_name")
    @classmethod
    def _normalize_spell_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("spell_name must not be blank")
        return normalized

    @field_validator("start_line", mode="before")
    @classmethod
    def _parse_start_line(cls, value: Any) -> Any:
        return _parse_absolute_start_line(value)


class _DocumentedDiscoveryPageResponse(BaseModel):
    active_heading: str | None
    end_of_spells_section: bool
    spells: list[_DocumentedDiscoverySpell]

    @field_validator("active_heading")
    @classmethod
    def _normalize_active_heading(cls, value: str | None) -> str | None:
        return _normalize_active_heading(value)


class _LegacyDiscoveryPageResponse(BaseModel):
    spell_starts: list[DiscoverySpellStart]
    active_heading: str | None
    end_of_spells_section: bool

    @field_validator("active_heading")
    @classmethod
    def _normalize_active_heading(cls, value: str | None) -> str | None:
        return _normalize_active_heading(value)


class DiscoveryPageResponse(BaseModel):
    spell_starts: list[DiscoverySpellStart] = Field(default_factory=list)
    active_heading: str | None = None
    end_of_spells_section: bool = False

    @field_validator("active_heading")
    @classmethod
    def _normalize_active_heading(cls, value: str | None) -> str | None:
        return _normalize_active_heading(value)

    @field_validator("spell_starts")
    @classmethod
    def _sort_spell_starts(
        cls,
        value: list[DiscoverySpellStart],
    ) -> list[DiscoverySpellStart]:
        sorted_starts = sorted(value, key=lambda item: item.start_line)

        duplicate_start_lines: list[str] = []
        previous_start_line: int | None = None
        for spell_start in sorted_starts:
            if spell_start.start_line == previous_start_line:
                duplicate_start_lines.append(str(spell_start.start_line))
            previous_start_line = spell_start.start_line

        if duplicate_start_lines:
            duplicate_values = ", ".join(duplicate_start_lines)
            raise ValueError(f"duplicate start_line values are not allowed: {duplicate_values}")

        return sorted_starts


@dataclass(frozen=True)
class DiscoveryPageInput:
    page_index: int
    start_line: int
    end_line: int
    prior_active_heading: str | None
    prompt: str
    numbered_page_text: str


@dataclass(frozen=True)
class _DocumentPage:
    page_index: int
    start_line: int
    end_line: int
    lines: list[str]


@dataclass
class _OpenSpellSpan:
    start_line: int
    context_heading: str | None


class DiscoveryInterruptedError(RuntimeError):
    def __init__(self, message: str, *, partial_session_state: SessionState) -> None:
        super().__init__(message)
        self.partial_session_state = partial_session_state


DiscoveryPageCaller = Callable[[DiscoveryPageInput], DiscoveryPageResponse]


def number_markdown_lines(lines: Sequence[str], *, start_line: int) -> str:
    if start_line < 0:
        raise ValueError("start_line must be non-negative")
    return "\n".join(f"{start_line + index}: {line}" for index, line in enumerate(lines))


def _normalize_active_heading(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _page_has_continuation_content(lines: Sequence[str]) -> bool:
    return any(line.strip() for line in lines)


def parse_discovery_response(raw_response: str) -> DiscoveryPageResponse:
    payload_text = raw_response.strip()
    fenced_match = _FENCED_JSON_RE.match(payload_text)
    if fenced_match is not None:
        payload_text = fenced_match.group("body").strip()

    if not payload_text.startswith("{"):
        start_index = payload_text.find("{")
        end_index = payload_text.rfind("}")
        if start_index >= 0 and end_index >= start_index:
            payload_text = payload_text[start_index : end_index + 1]

    payload = json.loads(payload_text)
    if "spells" in payload:
        documented_response = _DocumentedDiscoveryPageResponse.model_validate(payload)
        return DiscoveryPageResponse(
            spell_starts=[
                DiscoverySpellStart(
                    spell_name=spell.spell_name,
                    start_line=spell.start_line,
                )
                for spell in documented_response.spells
            ],
            active_heading=documented_response.active_heading,
            end_of_spells_section=documented_response.end_of_spells_section,
        )

    if "spell_starts" in payload:
        legacy_response = _LegacyDiscoveryPageResponse.model_validate(payload)
        return DiscoveryPageResponse.model_validate(legacy_response.model_dump())

    _DocumentedDiscoveryPageResponse.model_validate(payload)
    raise AssertionError("unreachable")


def detect_spells(
    routed_document: RoutedDocument,
    *,
    config: AppConfig,
    page_caller: DiscoveryPageCaller | None = None,
    session_state: SessionState | None = None,
) -> SessionState:
    if session_state is not None and session_state.source_sha256_hex != routed_document.source_sha256_hex:
        raise ValueError("session_state source hash does not match routed_document")

    working_session = _build_working_session(routed_document, session_state=session_state)

    discovery_page_caller = page_caller or _build_default_page_caller(config)

    restored_pending_records = [
        record.model_copy(deep=True)
        for record in working_session.records
        if record.status == SpellRecordStatus.PENDING_EXTRACTION
    ]
    next_order = _next_record_order(working_session.records)

    preserved_records = [
        record for record in working_session.records if record.status != SpellRecordStatus.PENDING_EXTRACTION
    ]
    working_session.records = list(preserved_records)

    active_heading: str | None = None
    consecutive_empty_pages = 0
    empty_streak_start_line: int | None = None
    found_any_spell = False
    open_span: _OpenSpellSpan | None = None
    document_pages = _build_document_pages(routed_document)

    for page in document_pages:
        try:
            numbered_page_text = number_markdown_lines(page.lines, start_line=page.start_line)
            page_input = DiscoveryPageInput(
                page_index=page.page_index,
                start_line=page.start_line,
                end_line=page.end_line,
                prior_active_heading=active_heading,
                prompt=_build_stage1_prompt_from_numbered_page(
                    numbered_page_text,
                    prior_active_heading=active_heading,
                ),
                numbered_page_text=numbered_page_text,
            )
            response = discovery_page_caller(page_input)
            if response.active_heading is not None:
                active_heading = response.active_heading

            page_has_starts = bool(response.spell_starts)
            page_has_effective_heading = response.active_heading is not None
            if not page_has_effective_heading and active_heading is not None:
                page_has_effective_heading = _page_has_continuation_content(page.lines)
            if page_has_starts:
                found_any_spell = True

            for spell_start in response.spell_starts:
                if spell_start.start_line < page.start_line or spell_start.start_line >= page.end_line:
                    raise ValueError(
                        f"Stage 1 returned start_line {spell_start.start_line} outside page range "
                        f"[{page.start_line}, {page.end_line})."
                    )
                if open_span is not None:
                    next_order = _close_open_span(
                        working_session,
                        open_span=open_span,
                        end_line=spell_start.start_line,
                        order=next_order,
                    )
                open_span = _OpenSpellSpan(
                    start_line=spell_start.start_line,
                    context_heading=active_heading,
                )

            if response.end_of_spells_section:
                if open_span is not None:
                    next_order = _close_open_span(
                        working_session,
                        open_span=open_span,
                        end_line=page.end_line if page_has_starts else page.start_line,
                        order=next_order,
                    )
                    open_span = None
                break

            if page_has_effective_heading or page_has_starts:
                consecutive_empty_pages = 0
                empty_streak_start_line = None
            elif found_any_spell and config.stage1_empty_page_cutoff > 0:
                if consecutive_empty_pages == 0:
                    empty_streak_start_line = page.start_line
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= config.stage1_empty_page_cutoff:
                    if open_span is not None:
                        next_order = _close_open_span(
                            working_session,
                            open_span=open_span,
                            end_line=(
                                empty_streak_start_line
                                if empty_streak_start_line is not None
                                else page.start_line
                            ),
                            order=next_order,
                        )
                        open_span = None
                    break
        except DiscoveryInterruptedError:
            raise
        except Exception as exc:
            raise DiscoveryInterruptedError(
                str(exc),
                partial_session_state=_snapshot_interrupted_session_state(
                    working_session,
                    restored_pending_records=restored_pending_records,
                ),
            ) from exc

    if open_span is not None:
        _close_open_span(
            working_session,
            open_span=open_span,
            end_line=len(routed_document.coordinate_map.lines),
            order=next_order,
        )

    _clear_stale_selected_spell(working_session)
    return working_session


def restore_discovery_session(
    routed_document: RoutedDocument,
    *,
    session_path: str | Path | None = None,
) -> SessionState | None:
    restored_session = restore_session_state_for_source(
        routed_document.source_sha256_hex,
        session_path=session_path,
    )
    if restored_session is None:
        return None
    return _build_working_session(routed_document, session_state=restored_session)


def open_or_restore_discovery_session(
    routed_document: RoutedDocument,
    *,
    config: AppConfig,
    page_caller: DiscoveryPageCaller | None = None,
    session_path: str | Path | None = None,
) -> SessionState:
    restored_session = restore_discovery_session(
        routed_document,
        session_path=session_path,
    )
    if restored_session is not None and _session_has_pending_records(restored_session):
        save_session_state(restored_session, session_path=session_path)
        return restored_session

    return detect_spells_with_autosave(
        routed_document,
        config=config,
        page_caller=page_caller,
        session_state=restored_session,
        session_path=session_path,
    )


def detect_spells_with_autosave(
    routed_document: RoutedDocument,
    *,
    config: AppConfig,
    page_caller: DiscoveryPageCaller | None = None,
    session_state: SessionState | None = None,
    session_path: str | Path | None = None,
) -> SessionState:
    if session_state is None:
        restored_session = restore_discovery_session(
            routed_document,
            session_path=session_path,
        )
        if restored_session is not None:
            if _session_has_pending_records(restored_session):
                save_session_state(restored_session, session_path=session_path)
                return restored_session
            session_state = restored_session

    try:
        discovered_session = detect_spells(
            routed_document,
            config=config,
            page_caller=page_caller,
            session_state=session_state,
        )
    except DiscoveryInterruptedError as exc:
        save_session_state(exc.partial_session_state, session_path=session_path)
        raise

    save_session_state(discovered_session, session_path=session_path)
    return discovered_session


def _build_working_session(
    routed_document: RoutedDocument,
    *,
    session_state: SessionState | None,
) -> SessionState:
    if session_state is None:
        return SessionState(
            source_sha256_hex=routed_document.source_sha256_hex,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[],
        )

    working_session = session_state.model_copy(deep=True)
    working_session.last_open_path = str(routed_document.source_path)
    working_session.coordinate_map = _select_working_coordinate_map(
        restored_coordinate_map=working_session.coordinate_map,
        routed_coordinate_map=routed_document.coordinate_map,
        restored_records=working_session.records,
    )
    working_session.records = _normalize_restored_record_boundaries(
        working_session.records,
        line_count=len(working_session.coordinate_map.lines),
    )
    _clear_stale_selected_spell(working_session)
    return working_session


def _select_working_coordinate_map(
    *,
    restored_coordinate_map: CoordinateAwareTextMap,
    routed_coordinate_map: CoordinateAwareTextMap,
    restored_records: Sequence[SpellRecord],
) -> CoordinateAwareTextMap:
    if routed_coordinate_map.lines:
        return routed_coordinate_map
    if restored_records and restored_coordinate_map.lines:
        return restored_coordinate_map
    return routed_coordinate_map


def _normalize_restored_record_boundaries(
    records: Sequence[SpellRecord],
    *,
    line_count: int,
) -> list[SpellRecord]:
    normalized_records: list[SpellRecord] = []
    for record in records:
        normalized_record = _normalize_restored_record_boundary(record, line_count=line_count)
        if normalized_record is not None:
            normalized_records.append(normalized_record)
    return normalized_records


def _normalize_restored_record_boundary(
    record: SpellRecord,
    *,
    line_count: int,
) -> SpellRecord | None:
    if line_count <= 0:
        return record

    normalized_start = min(record.boundary_start_line, line_count - 1)
    if record.boundary_end_line < 0:
        normalized_end = line_count
    else:
        normalized_end = min(record.boundary_end_line, line_count)
    normalized_end = max(normalized_end, normalized_start + 1)
    normalized_end = min(normalized_end, line_count)

    if normalized_start == record.boundary_start_line and normalized_end == record.boundary_end_line:
        return record

    return record.model_copy(
        update={
            "boundary_start_line": normalized_start,
            "boundary_end_line": normalized_end,
        }
    )


def _session_has_pending_records(session_state: SessionState) -> bool:
    return any(record.status == SpellRecordStatus.PENDING_EXTRACTION for record in session_state.records)


def _clear_stale_selected_spell(session_state: SessionState) -> None:
    if session_state.selected_spell_id is None:
        return

    record_ids = {record.spell_id for record in session_state.records}
    if session_state.selected_spell_id not in record_ids:
        session_state.selected_spell_id = None


def _snapshot_session_state(session_state: SessionState) -> SessionState:
    snapshot = session_state.model_copy(deep=True)
    _clear_stale_selected_spell(snapshot)
    return snapshot


def _snapshot_interrupted_session_state(
    session_state: SessionState,
    *,
    restored_pending_records: Sequence[SpellRecord],
) -> SessionState:
    if not restored_pending_records:
        return _snapshot_session_state(session_state)

    snapshot = session_state.model_copy(deep=True)

    current_pending_records: list[SpellRecord] = []
    current_pending_boundaries: set[int] = set()
    stable_records: list[SpellRecord] = []
    for record in snapshot.records:
        if record.status == SpellRecordStatus.PENDING_EXTRACTION:
            current_pending_records.append(record)
            current_pending_boundaries.add(record.boundary_start_line)
            continue
        stable_records.append(record)

    preserved_pending_records = [
        record.model_copy(deep=True)
        for record in restored_pending_records
        if record.boundary_start_line not in current_pending_boundaries
    ]
    snapshot.records = [*stable_records, *preserved_pending_records, *current_pending_records]
    _clear_stale_selected_spell(snapshot)
    return snapshot


def _append_pending_record(
    session_state: SessionState,
    *,
    start_line: int,
    end_line: int,
    context_heading: str | None,
    order: int,
) -> bool:
    if end_line <= start_line:
        return False

    spell_id = _build_pending_spell_id(
        source_sha256_hex=session_state.source_sha256_hex,
        start_line=start_line,
    )

    for record in session_state.records:
        if record.spell_id == spell_id:
            return False
        if record.status == SpellRecordStatus.PENDING_EXTRACTION:
            continue
        if record.boundary_start_line == start_line:
            return False

    session_state.records.append(
        SpellRecord(
            spell_id=spell_id,
            status=SpellRecordStatus.PENDING_EXTRACTION,
            extraction_order=order,
            section_order=order,
            boundary_start_line=start_line,
            boundary_end_line=end_line,
            context_heading=context_heading,
        )
    )
    return True


def _close_open_span(
    session_state: SessionState,
    *,
    open_span: _OpenSpellSpan,
    end_line: int,
    order: int,
) -> int:
    if _append_pending_record(
        session_state,
        start_line=open_span.start_line,
        end_line=end_line,
        context_heading=open_span.context_heading,
        order=order,
    ):
        return order + 1
    return order


def _next_record_order(records: Sequence[SpellRecord]) -> int:
    if not records:
        return 0
    return max(
        max(record.extraction_order, record.section_order) for record in records
    ) + 1


def _build_pending_spell_id(*, source_sha256_hex: str, start_line: int) -> str:
    return f"pending-{source_sha256_hex}-{start_line:06d}"


def _build_document_pages(routed_document: RoutedDocument) -> list[_DocumentPage]:
    document_pages: list[_DocumentPage] = []
    current_lines: list[str] = []
    current_group: object | None = None
    current_start_line = 0

    for absolute_line, (line, region) in enumerate(routed_document.coordinate_map.lines):
        page_group = _logical_page_group(routed_document, absolute_line, region.page)
        if current_group is None:
            current_group = page_group
            current_start_line = absolute_line

        if page_group != current_group:
            document_pages.append(
                _DocumentPage(
                    page_index=len(document_pages),
                    start_line=current_start_line,
                    end_line=absolute_line,
                    lines=current_lines,
                )
            )
            current_group = page_group
            current_start_line = absolute_line
            current_lines = []

        current_lines.append(line)

    if current_group is not None:
        document_pages.append(
            _DocumentPage(
                page_index=len(document_pages),
                start_line=current_start_line,
                end_line=len(routed_document.coordinate_map.lines),
                lines=current_lines,
            )
        )

    return document_pages


def _logical_page_group(
    routed_document: RoutedDocument,
    line_index: int,
    region_page: int,
) -> object:
    if region_page >= 0:
        return region_page
    if line_index < len(routed_document.default_source_pages):
        default_page = routed_document.default_source_pages[line_index]
        if default_page is not None:
            return default_page
    if routed_document.file_type == "docx":
        return ("docx-chunk", line_index // _DOCX_FALLBACK_CHUNK_LINE_COUNT)
    return 0


def _build_stage1_prompt(
    lines: Sequence[str],
    *,
    start_line: int,
    prior_active_heading: str | None,
) -> str:
    numbered_page = number_markdown_lines(lines, start_line=start_line)
    return _build_stage1_prompt_from_numbered_page(
        numbered_page,
        prior_active_heading=prior_active_heading,
    )


def _build_stage1_prompt_from_numbered_page(
    numbered_page: str,
    *,
    prior_active_heading: str | None,
) -> str:
    prior_heading_payload = json.dumps(
        {"prior_active_heading": prior_active_heading},
        ensure_ascii=True,
    )
    return (
        "You are performing Stage 1 spell discovery. Prior heading context from the previous page:\n"
        f"{prior_heading_payload}\n"
        "Use prior_active_heading as carry-forward context from the previous page. "
        "If prior_active_heading is non-null, it is the heading already active when this page begins unless the current page shows a replacement heading. "
        "Return one JSON object in this exact shape:\n"
        '{"active_heading": null, "end_of_spells_section": false, '
        '"spells": [{"spell_name": "Magic Missile", "start_line": "001"}]}\n'
        "Set end_of_spells_section to true if the page clearly transitions out of a spell listing into another major topic, such as a new chapter, an appendix, or the end of the book. "
        'Return active_heading when the current page introduces a spell-section heading or replaces the carried heading. '
        'Return null for active_heading when this page does not introduce a heading update. Returning null keeps prior_active_heading unchanged. '
        "Always include all three top-level keys. Use an empty spells array when no spell starts are present. "
        "Copy the absolute zero-based line number from the numbered page text into each start_line string.\n\n"
        f"{numbered_page}"
    )


def _build_stage1_user_message(page_input: DiscoveryPageInput) -> str:
    return page_input.prompt


def _build_default_page_caller(config: AppConfig) -> DiscoveryPageCaller:
    anthropic_module = _load_optional_module("anthropic")
    api_key = _resolve_anthropic_api_key(config)
    client = anthropic_module.Anthropic(api_key=api_key)

    def call_page(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
        message = client.messages.create(
            model=config.stage1_model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _STAGE1_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _build_stage1_user_message(page_input)}],
        )
        response_text = _extract_anthropic_text(message)
        return parse_discovery_response(response_text)

    return call_page


def _load_optional_module(module_name: str) -> Any:
    try:
        return import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"{module_name} is required for Stage 1 discovery but is not installed.") from exc


def _coerce_api_key_storage_mode(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"env", "credential_manager", "local_plaintext"}:
            return normalized
    return "env"


def _resolve_anthropic_api_key(config: AppConfig) -> str:
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key

    storage_mode = _coerce_api_key_storage_mode(config.api_key_storage_mode)

    if storage_mode == "local_plaintext":
        plaintext_key = config.api_key.strip() if isinstance(config.api_key, str) else ""
        if plaintext_key:
            return plaintext_key

    elif storage_mode == "credential_manager":
        keyring_key = _read_keyring_api_key_safely()
        if keyring_key:
            return keyring_key

    raise RuntimeError("No Anthropic API key is configured for Stage 1 discovery.")


def _read_keyring_api_key_safely() -> str:
    with suppress(Exception):
        return _read_keyring_api_key()
    return ""


def _read_keyring_api_key() -> str:
    try:
        keyring_module = import_module("keyring")
    except ImportError:
        return ""

    key_value: object = None
    with suppress(Exception):
        key_value = keyring_module.get_password(CREDENTIAL_SERVICE_NAME, CREDENTIAL_ACCOUNT_NAME)

    if not isinstance(key_value, str):
        return ""
    return key_value.strip()


def _extract_anthropic_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, list):
        text_parts = []
        for item in content:
            text_value = getattr(item, "text", None)
            if isinstance(text_value, str):
                text_parts.append(text_value)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        if text_parts:
            return "\n".join(text_parts)
    raise RuntimeError("Anthropic Stage 1 response did not include text content.")