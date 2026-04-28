"""QObject-based workers for background extraction jobs."""
from __future__ import annotations

from copy import deepcopy
import threading
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QObject, Signal

from app.pipeline.extraction import detect_spells, extract_all_pending, extract_selected_pending

if TYPE_CHECKING:
    from app.config import AppConfig
    from app.pipeline.ingestion import RoutedDocument
    from app.session import SessionState


def _clone_session_state(session_state: SessionState) -> SessionState:
    """Return an isolated session copy for background pipeline mutation."""
    return deepcopy(session_state)


class DetectSpellsWorker(QObject):
    """Runs detect_spells() on a background thread."""

    spells_detected = Signal(int)
    session_ready = Signal(object)
    progress_updated = Signal(int, int)
    cancelled = Signal()
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        routed_document: RoutedDocument,
        config: AppConfig,
        session_state: SessionState,
        cancel_event: threading.Event,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._routed_document = routed_document
        self._config = config
        self._session_state = session_state
        self._cancel_event = cancel_event

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return

        working_session = _clone_session_state(self._session_state)
        self.progress_updated.emit(0, 1)

        try:
            result = detect_spells(
                self._routed_document,
                config=self._config,
                session_state=working_session,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("Detection Failed", str(exc))
            return

        if self._cancel_event.is_set():
            self.progress_updated.emit(1, 1)
            self.session_ready.emit(result)
            pending_count = sum(
                1 for record in result.records if record.status.value == "pending_extraction"
            )
            self.spells_detected.emit(pending_count)
            self.cancelled.emit()
            return

        pending_count = sum(
            1 for record in result.records if record.status.value == "pending_extraction"
        )
        self.progress_updated.emit(1, 1)
        self.session_ready.emit(result)
        self.spells_detected.emit(pending_count)


class ExtractWorker(QObject):
    """Runs extraction for all or selected pending records on a background thread."""

    record_extracted = Signal(str)
    extraction_complete = Signal(object)
    progress_updated = Signal(int, int)
    extraction_cancelled = Signal()
    extraction_failed = Signal(str, str)
    cancelled = Signal()
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        session_state: SessionState,
        config: AppConfig,
        cancel_event: threading.Event,
        mode: Literal["all", "selected"],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_state = session_state
        self._config = config
        self._cancel_event = cancel_event
        self._mode = mode

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.extraction_cancelled.emit()
            self.cancelled.emit()
            return

        working_session = _clone_session_state(self._session_state)

        pending_before = {
            record.spell_id
            for record in working_session.records
            if record.status.value == "pending_extraction"
        }
        if self._mode == "selected":
            selected_spell_id = getattr(working_session, "selected_spell_id", None)
            if isinstance(selected_spell_id, str) and selected_spell_id in pending_before:
                extraction_scope = {selected_spell_id}
            else:
                extraction_scope = set()
        else:
            extraction_scope = pending_before

        pending_total = len(extraction_scope)
        self.progress_updated.emit(0, pending_total)

        try:
            if self._mode == "all":
                result = extract_all_pending(working_session, config=self._config)
            else:
                result = extract_selected_pending(working_session, config=self._config)
        except Exception as exc:  # noqa: BLE001
            self.extraction_failed.emit("Extraction Failed", str(exc))
            self.failed.emit("Extraction Failed", str(exc))
            return

        processed_ids = {
            record.spell_id
            for record in result.records
            if record.status.value != "pending_extraction" and record.spell_id in extraction_scope
        }
        completed_count = len(processed_ids)

        if self._cancel_event.is_set():
            # Preserve completed work from the blocking extraction call.
            self.progress_updated.emit(completed_count, pending_total)
            self.extraction_complete.emit(result)
            self.extraction_cancelled.emit()
            self.cancelled.emit()
            return

        for record in result.records:
            if record.spell_id in processed_ids:
                self.record_extracted.emit(record.spell_id)

        self.progress_updated.emit(completed_count, pending_total)
        self.extraction_complete.emit(result)
