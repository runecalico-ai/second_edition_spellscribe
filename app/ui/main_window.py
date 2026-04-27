"""SpellScribe main application window."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QWidget,
)

import fitz

from app.pipeline.identity import compute_sha256_hex
from app.pipeline.ingestion import route_document
from app.config import AppConfig
from app.session import SessionState, restore_session_state_for_source
from app.ui.identity_dialog import DocumentIdentityDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.workers import DetectSpellsWorker, ExtractWorker

if TYPE_CHECKING:
    from app.config import AppConfig


class SpellScribeMainWindow(QMainWindow):
    """Three-panel workbench: document | spell list | review."""

    def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._session: SessionState | None = None
        self._worker_running = False
        self._active_worker: object | None = None
        self._active_thread: QThread | None = None
        self._cancel_event: threading.Event = threading.Event()
        self._routed_document = None

        self.setWindowTitle("SpellScribe")
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_bar()
        self._update_action_states()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        self._action_open = tb.addAction("Open File")
        self._action_open.triggered.connect(self._on_open_file)

        tb.addSeparator()

        self._action_detect = tb.addAction("Detect Spells")
        self._action_detect.triggered.connect(self._on_detect_spells)

        self._action_extract_selected = tb.addAction("Extract Selected")
        self._action_extract_selected.triggered.connect(self._on_extract_selected)

        self._action_extract_all = tb.addAction("Extract All Pending")
        self._action_extract_all.triggered.connect(self._on_extract_all)

        self._action_cancel = tb.addAction("Cancel")
        self._action_cancel.triggered.connect(self._on_cancel)

        tb.addSeparator()

        self._action_export = tb.addAction("Export")
        self._action_export.setToolTip(
            "Export not available in this build - "
            "the export dialog will be added in a future change."
        )
        self._action_export.setEnabled(False)
        self._action_export.triggered.connect(self._on_export)

        tb.addSeparator()

        self._action_settings = tb.addAction("Settings")
        self._action_settings.triggered.connect(self._on_settings)

    def _update_action_states(self) -> None:
        has_session = self._session is not None
        worker_active = self._worker_running

        self._action_open.setEnabled(not worker_active)
        self._action_detect.setEnabled(has_session and not worker_active)
        self._action_extract_selected.setEnabled(has_session and not worker_active)
        self._action_extract_all.setEnabled(has_session and not worker_active)
        self._action_cancel.setEnabled(worker_active)
        self._action_settings.setEnabled(not worker_active)

    def _build_central_widget(self) -> None:
        from app.ui.document_panel import DocumentPanel
        from app.ui.review_panel import ReviewPanel
        from app.ui.spell_list_panel import SpellListPanel

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self._doc_panel = DocumentPanel(self)
        splitter.addWidget(self._doc_panel)

        self._spell_list_panel = SpellListPanel(self)
        self._spell_list_panel.selected_spell_id_changed.connect(self._on_spell_selected)
        splitter.addWidget(self._spell_list_panel)

        self._review_panel = ReviewPanel(config=self._config, parent=self)
        self._review_panel.session_changed.connect(self._on_review_session_changed)
        splitter.addWidget(self._review_panel)

        splitter.setSizes([400, 200, 350])
        self.setCentralWidget(splitter)

    def _build_status_bar(self) -> None:
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

    def _set_session(self, session: SessionState, *, source_path: str) -> None:
        self._session = session
        filename = Path(source_path).name
        self.setWindowTitle(f"{filename} - SpellScribe")
        self._update_action_states()
        self._refresh_panels_from_session_selection()

    def _on_review_session_changed(self, updated_session: SessionState) -> None:
        self._session = updated_session
        self._refresh_panels_from_session_selection()

    def _refresh_panels_from_session_selection(self) -> None:
        if self._session is None:
            return

        restored_spell_id = self._spell_list_panel.refresh(
            self._session,
            selected_spell_id=self._session.selected_spell_id,
        )
        if restored_spell_id is None:
            self._on_spell_selected("")
            return
        self._on_spell_selected(restored_spell_id)

    def _on_spell_selected(self, spell_id: str) -> None:
        if self._session is None:
            return

        if spell_id == "":
            self._session.selected_spell_id = None
            self._review_panel.show_placeholder()
            self._doc_panel.show_placeholder()
            return

        record = next((r for r in self._session.records if r.spell_id == spell_id), None)
        if record is None:
            return

        self._session.selected_spell_id = spell_id

        if record.status.value == "pending_extraction":
            self._review_panel.show_pending_record(record)
        else:
            self._review_panel.show_review_record(record, self._session)

        if record.boundary_end_line < 0:
            self._doc_panel.show_placeholder()
            return

        regions = self._session.coordinate_map.regions_for_range(
            record.boundary_start_line,
            record.boundary_end_line,
        )
        if not regions:
            self._doc_panel.show_placeholder()
            return

        first = regions[0]
        if first.page >= 0:
            if self._routed_document is None:
                self._doc_panel.show_placeholder()
                return
            try:
                with fitz.open(self._session.last_open_path) as doc:
                    page_regions = [region for region in regions if region.page == first.page]
                    self._doc_panel.display_pdf_page(
                        doc,
                        page_num=first.page,
                        highlight_regions=page_regions,
                    )
            except Exception:  # noqa: BLE001
                self._doc_panel.show_placeholder()
            return

        char_ranges = [
            region.char_offset
            for region in regions
            if getattr(region, "char_offset", None) is not None
        ]
        markdown_text = (
            self._routed_document.markdown_text if self._routed_document is not None else ""
        )
        self._doc_panel.display_docx(markdown_text, highlight_ranges=char_ranges)

    def _on_open_file(self) -> None:
        start_dir = getattr(self._config, "last_import_directory", "") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Document",
            start_dir,
            "Documents (*.pdf *.docx)",
        )
        if not path:
            return
        self._open_document(path)

    def _open_document(self, path: str) -> None:
        try:
            sha256 = compute_sha256_hex(path)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot Open File", str(exc))
            return

        if self._session is not None and self._session.source_sha256_hex == sha256:
            try:
                routed = route_document(path, config=self._config)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Open Failed", str(exc))
                return

            self._routed_document = routed
            self._session.last_open_path = path
            self._session.coordinate_map = routed.coordinate_map
            filename = Path(path).name
            self.setWindowTitle(f"{filename} - SpellScribe")
            self._config.last_import_directory = str(Path(path).parent)
            self._status_bar.showMessage(f"Reopened: {filename}")
            return

        if self._session is not None:
            has_committed = any(
                record.status.value in ("confirmed", "needs_review")
                for record in self._session.records
            )
            if has_committed:
                box = QMessageBox(self)
                box.setWindowTitle("Open Different Document")
                box.setText(
                    "You have confirmed or review-state records for the current document."
                )
                export_btn = box.addButton("Export...", QMessageBox.ButtonRole.ActionRole)
                discard_btn = box.addButton(
                    "Discard and Open", QMessageBox.ButtonRole.DestructiveRole
                )
                cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                box.exec()

                clicked = box.clickedButton()
                if clicked is export_btn:
                    self._on_export()
                    return
                if clicked is cancel_btn or clicked is None:
                    return
                if clicked is not discard_btn:
                    return

        session = restore_session_state_for_source(sha256)

        if session is None:
            if sha256 not in getattr(self._config, "document_names_by_sha256", {}):
                dlg = DocumentIdentityDialog(
                    sha256_hex=sha256,
                    default_document_name=getattr(
                        self._config,
                        "default_source_document",
                        "",
                    ),
                    parent=self,
                )
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return

                identity_result = dlg.get_result()
                self._config.document_names_by_sha256[sha256] = identity_result.source_display_name
                if identity_result.page_offset:
                    self._config.document_offsets[sha256] = identity_result.page_offset
                if identity_result.force_ocr:
                    self._config.force_ocr_by_sha256[sha256] = True

            try:
                routed = route_document(path, config=self._config)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Open Failed", str(exc))
                return

            self._routed_document = routed
            session = SessionState(
                source_sha256_hex=sha256,
                last_open_path=path,
                coordinate_map=routed.coordinate_map,
                records=[],
            )
        else:
            try:
                routed = route_document(path, config=self._config)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Open Failed", str(exc))
                return
            self._routed_document = routed
            session.last_open_path = path
            session.coordinate_map = routed.coordinate_map

        self._config.last_import_directory = str(Path(path).parent)
        self._set_session(session, source_path=path)
        self._status_bar.showMessage(f"Opened: {Path(path).name}")

    def _on_detect_spells(self) -> None:
        if self._session is None or self._routed_document is None:
            return

        self._cancel_event = threading.Event()
        worker = DetectSpellsWorker(
            routed_document=self._routed_document,
            config=self._config,
            session_state=self._session,
            cancel_event=self._cancel_event,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.session_ready.connect(self._on_session_ready)
        worker.spells_detected.connect(self._on_spells_detected)
        worker.failed.connect(self._on_worker_failed)
        worker.cancelled.connect(self._on_worker_cancelled)
        worker.spells_detected.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._active_thread = thread
        self._active_worker = worker
        self._worker_running = True
        self._update_action_states()
        thread.start()

    def _on_extract_selected(self) -> None:
        self._start_extract_worker(mode="selected")

    def _on_extract_all(self) -> None:
        self._start_extract_worker(mode="all")

    def _start_extract_worker(self, mode: str) -> None:
        if self._session is None:
            return

        self._cancel_event = threading.Event()
        worker = ExtractWorker(
            session_state=self._session,
            config=self._config,
            cancel_event=self._cancel_event,
            mode=mode,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.record_extracted.connect(self._on_record_extracted)
        worker.extraction_complete.connect(self._on_extraction_complete)
        worker.failed.connect(self._on_worker_failed)
        worker.cancelled.connect(self._on_worker_cancelled)
        worker.extraction_complete.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._active_thread = thread
        self._active_worker = worker
        self._worker_running = True
        self._update_action_states()
        thread.start()

    def _on_cancel(self) -> None:
        self._cancel_event.set()

    def _on_spells_detected(self, count: int) -> None:
        self._active_worker = None
        self._active_thread = None
        self._worker_running = False
        self._update_action_states()
        self._status_bar.showMessage(
            f"Detection complete - {count} spell(s) pending extraction."
        )
        if hasattr(self, "_spell_list_panel") and self._session is not None:
            self._refresh_panels_from_session_selection()

    def _on_record_extracted(self, spell_id: str) -> None:
        self._status_bar.showMessage(f"Extracted: {spell_id}")
        self._update_action_states()

    def _on_extraction_complete(self, updated_session: SessionState) -> None:
        self._session = updated_session
        self._active_worker = None
        self._active_thread = None
        self._worker_running = False
        self._update_action_states()

        extracted_count = sum(
            1 for record in updated_session.records if record.status.value != "pending_extraction"
        )
        self._status_bar.showMessage(
            f"Extraction complete - {extracted_count} spell(s) extracted."
        )
        if hasattr(self, "_spell_list_panel"):
            self._refresh_panels_from_session_selection()

    def _on_worker_failed(self, title: str, message: str) -> None:
        self._active_worker = None
        self._active_thread = None
        self._worker_running = False
        self._update_action_states()
        QMessageBox.critical(self, title, message)

    def _on_worker_cancelled(self) -> None:
        if not self._worker_running:
            return
        self._active_worker = None
        self._active_thread = None
        self._worker_running = False
        self._update_action_states()
        self._status_bar.showMessage("Operation cancelled.")

    def _on_session_ready(self, new_session: SessionState) -> None:
        self._session = new_session

    def _on_export(self) -> None:
        QMessageBox.information(
            self,
            "Export",
            "Export is not available in this build. Integrate the export dialog to enable.",
        )

    def _on_settings(self) -> None:
        dlg = SettingsDialog(config=self._config, parent=self)
        dlg.exec()


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    config = AppConfig.load()
    window = SpellScribeMainWindow(config=config)
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec())
