from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.models import CoordinateAwareTextMap, Spell
from app.paths import spellscribe_data_dir


class SpellRecordStatus(str, Enum):
    PENDING_EXTRACTION = "pending_extraction"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"


class SpellRecord(BaseModel):
    spell_id: str
    status: SpellRecordStatus
    extraction_order: int
    section_order: int
    boundary_start_line: int
    boundary_end_line: int = -1
    context_heading: str | None = None
    manual_source_page_override: bool = False
    canonical_spell: Spell | None = None
    draft_spell: Spell | None = None
    draft_dirty: bool = False

    @model_validator(mode="after")
    def _validate_invariants(self) -> SpellRecord:
        if self.extraction_order < 0:
            raise ValueError("extraction_order must be non-negative")
        if self.section_order < 0:
            raise ValueError("section_order must be non-negative")
        if self.boundary_start_line < 0:
            raise ValueError("boundary_start_line must be non-negative")
        if self.boundary_end_line != -1 and self.boundary_end_line < self.boundary_start_line:
            raise ValueError(
                "boundary_end_line must be -1 or greater than or equal to boundary_start_line"
            )
        if self.status == SpellRecordStatus.CONFIRMED and self.canonical_spell is None:
            raise ValueError("canonical_spell must be present when status is confirmed")
        if self.draft_dirty and self.draft_spell is None:
            raise ValueError("draft_spell must be present when draft_dirty is true")
        return self


class SessionState(BaseModel):
    version: str = "1"
    source_sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_open_path: str
    coordinate_map: CoordinateAwareTextMap
    records: list[SpellRecord]
    selected_spell_id: str | None = None

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if value != "1":
            raise ValueError("version must be '1'")
        return value

    @model_validator(mode="after")
    def _validate_selected_spell_id(self) -> SessionState:
        record_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        for record in self.records:
            if record.spell_id in record_ids:
                duplicate_ids.add(record.spell_id)
            else:
                record_ids.add(record.spell_id)

        if duplicate_ids:
            duplicate_values = ", ".join(sorted(duplicate_ids))
            raise ValueError(
                f"records must contain unique spell_id values; duplicates: {duplicate_values}"
            )

        if self.selected_spell_id is None:
            return self

        if self.selected_spell_id not in record_ids:
            raise ValueError(
                "selected_spell_id must match a spell_id in records when provided"
            )

        return self


_SESSION_FILE_NAME = "session.json"


def default_session_path() -> Path:
    return spellscribe_data_dir() / _SESSION_FILE_NAME


def save_session_state(
    session_state: SessionState,
    session_path: str | Path | None = None,
) -> Path:
    destination = Path(session_path) if session_path is not None else default_session_path()
    destination.parent.mkdir(parents=True, exist_ok=True)

    payload = session_state.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=True, indent=2)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise

    return destination


def load_session_state(session_path: str | Path | None = None) -> SessionState | None:
    destination = Path(session_path) if session_path is not None else default_session_path()

    if not destination.exists():
        return None

    try:
        with destination.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return SessionState.model_validate(payload)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
        _rename_bad_session_file(destination)
        return None
    except OSError:
        return None


def restore_session_state_for_source(
    source_sha256_hex: str,
    *,
    session_path: str | Path | None = None,
) -> SessionState | None:
    session_state = load_session_state(session_path=session_path)
    if session_state is None:
        return None
    if session_state.source_sha256_hex != source_sha256_hex.strip().lower():
        return None
    return session_state


def _rename_bad_session_file(session_path: Path) -> None:
    bad_path = _build_quarantine_path(session_path)
    try:
        os.replace(session_path, bad_path)
    except OSError:
        return


def _build_quarantine_path(session_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = session_path.with_name(f"{session_path.name}.bad.{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = session_path.with_name(f"{session_path.name}.bad.{timestamp}.{suffix}")
        suffix += 1
    return candidate