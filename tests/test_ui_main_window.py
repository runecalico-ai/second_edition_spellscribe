"""Tests for SpellScribeMainWindow shell and toolbar."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolBar

from app.models import CoordinateAwareTextMap

# Deferred import so QApplication is created before widgets
_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


class TestMainWindowToolbar(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_window(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "Player's Handbook"
        return SpellScribeMainWindow(config=config)

    def test_window_title_shows_spellscribe_with_no_session(self):
        win = self._make_window()
        self.assertIn("SpellScribe", win.windowTitle())

    def test_toolbar_has_expected_actions(self):
        win = self._make_window()
        action_texts = {a.text() for a in win.findChildren(QToolBar)[0].actions() if a.text()}
        for expected in (
            "Open File",
            "Detect Spells",
            "Extract Selected",
            "Extract All Pending",
            "Cancel",
            "Export",
            "Settings",
        ):
            self.assertIn(expected, action_texts, f"Missing toolbar action: {expected}")

    def test_extraction_actions_disabled_before_document_open(self):
        win = self._make_window()
        self.assertFalse(win._action_detect.isEnabled())
        self.assertFalse(win._action_extract_selected.isEnabled())
        self.assertFalse(win._action_extract_all.isEnabled())
        self.assertFalse(win._action_cancel.isEnabled())

    def test_open_action_always_enabled(self):
        win = self._make_window()
        self.assertTrue(win._action_open.isEnabled())

    def test_export_action_disabled_with_tooltip(self):
        win = self._make_window()
        self.assertFalse(win._action_export.isEnabled())
        self.assertIn("not available", win._action_export.toolTip().lower())

    def test_extraction_actions_enabled_after_session_loaded(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "Player's Handbook"
        win = SpellScribeMainWindow(config=config)
        # Simulate a loaded session
        session = MagicMock()
        session.last_open_path = "/tmp/test.pdf"
        win._set_session(session, source_path="/tmp/test.pdf")
        self.assertTrue(win._action_detect.isEnabled())
        self.assertTrue(win._action_extract_selected.isEnabled())
        self.assertTrue(win._action_extract_all.isEnabled())
        # Cancel remains disabled until a worker is running
        self.assertFalse(win._action_cancel.isEnabled())

    def test_window_title_updates_after_session_loaded(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "Player's Handbook"
        win = SpellScribeMainWindow(config=config)
        session = MagicMock()
        session.last_open_path = "/docs/phb.pdf"
        win._set_session(session, source_path="/docs/phb.pdf")
        self.assertIn("phb.pdf", win.windowTitle())
        self.assertIn("SpellScribe", win.windowTitle())

    def test_settings_action_opens_settings_dialog(self):
        win = self._make_window()
        with patch("app.ui.main_window.SettingsDialog") as mock_dlg_cls:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            win._on_settings()
            mock_dlg_cls.assert_called_once()
            mock_dlg.exec.assert_called_once()


class TestDocumentPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel(self):
        from app.ui.document_panel import DocumentPanel

        return DocumentPanel()

    def test_panel_shows_placeholder_by_default(self):
        panel = self._make_panel()
        self.assertTrue(panel._placeholder_label.isVisible())

    def test_show_placeholder_hides_viewer(self):
        panel = self._make_panel()
        panel.show_placeholder()
        self.assertTrue(panel._placeholder_label.isVisible())

    def test_display_docx_shows_text(self):
        panel = self._make_panel()
        panel.display_docx("# Hello\n\nWorld", highlight_ranges=[])
        self.assertFalse(panel._placeholder_label.isVisible())
        self.assertTrue(panel._docx_edit.isVisible())
        self.assertIn("Hello", panel._docx_edit.toPlainText())

    def test_display_docx_with_highlight_ranges(self):
        panel = self._make_panel()
        panel.display_docx("Hello World", highlight_ranges=[(0, 5)])
        selections = panel._docx_edit.extraSelections()
        self.assertGreater(len(selections), 0)

    def test_display_pdf_page_with_no_highlights(self):
        import fitz

        panel = self._make_panel()
        doc = fitz.open()
        doc.new_page(width=200, height=300)
        panel.display_pdf_page(doc, page_num=0, highlight_regions=[])
        self.assertFalse(panel._placeholder_label.isVisible())
        doc.close()

    def test_display_pdf_page_with_highlights_calls_get_pixmap_and_does_not_raise(self):
        panel = self._make_panel()
        fitz_doc = MagicMock()
        page = MagicMock()
        fitz_doc.__getitem__ = MagicMock(return_value=page)

        pixmap_mock = MagicMock()
        pixmap_mock.width = 10
        pixmap_mock.height = 10
        pixmap_mock.samples = bytes(300)
        pixmap_mock.n = 3
        pixmap_mock.stride = 30
        page.get_pixmap.return_value = pixmap_mock

        region = MagicMock()
        region.bbox = (2.0, 3.0, 8.0, 7.0)
        highlight_regions = [region]

        panel.display_pdf_page(fitz_doc, page_num=0, highlight_regions=highlight_regions)
        page.get_pixmap.assert_called_once()
        self.assertIsNotNone(panel._pdf_scroll.widget())


class TestSpellListPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel(self):
        from app.ui.spell_list_panel import SpellListPanel

        return SpellListPanel()

    def _make_session(self, records):
        session = MagicMock()
        session.records = records
        session.selected_spell_id = None
        return session

    def _make_record(self, spell_id, status_value, name="Magic Missile"):
        record = MagicMock()
        record.spell_id = spell_id
        record.status = MagicMock()
        record.status.value = status_value
        spell = MagicMock()
        spell.name = name
        record.canonical_spell = spell
        record.draft_spell = spell
        record.section_order = 0
        return record

    def test_panel_starts_empty(self):
        panel = self._make_panel()
        total = (
            panel._confirmed_list.count()
            + panel._needs_review_list.count()
            + panel._pending_list.count()
        )
        self.assertEqual(total, 0)

    def test_refresh_populates_confirmed_section(self):
        panel = self._make_panel()
        r = self._make_record("id-1", "confirmed", "Fireball")
        r.status = MagicMock(value="confirmed")
        r.canonical_spell.name = "Fireball"
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._confirmed_list.count(), 1)
        self.assertIn("Fireball", panel._confirmed_list.item(0).text())

    def test_refresh_populates_needs_review_section(self):
        panel = self._make_panel()
        r = self._make_record("id-2", "needs_review", "Sleep")
        r.status = MagicMock(value="needs_review")
        r.draft_spell.name = "Sleep"
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._needs_review_list.count(), 1)

    def test_refresh_populates_pending_section(self):
        panel = self._make_panel()
        r = self._make_record("id-3", "pending_extraction", "Unknown")
        r.status = MagicMock(value="pending_extraction")
        r.canonical_spell = None
        r.draft_spell = None
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._pending_list.count(), 1)

    def test_selection_emits_spell_id_signal(self):
        panel = self._make_panel()
        r = self._make_record("id-1", "confirmed", "Fireball")
        r.status = MagicMock(value="confirmed")
        r.canonical_spell.name = "Fireball"
        session = self._make_session([r])
        panel.refresh(session)

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))
        panel._confirmed_list.setCurrentRow(0)
        self.assertEqual(emitted, ["id-1"])


class TestReviewPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel(self):
        from app.ui.review_panel import ReviewPanel

        config = MagicMock()
        config.custom_schools = []
        config.custom_spheres = []
        return ReviewPanel(config=config)

    def _make_pending_record(self):
        record = MagicMock()
        record.spell_id = "abc-123"
        record.status = MagicMock(value="pending_extraction")
        record.canonical_spell = None
        record.draft_spell = None
        record.draft_dirty = False
        record.extraction_order = 5
        record.boundary_start_line = 100
        record.boundary_end_line = 120
        spell = MagicMock()
        spell.name = "Sleep"
        record.draft_spell = spell
        return record

    def _make_needs_review_record(self):
        record = MagicMock()
        record.spell_id = "def-456"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = False
        spell = MagicMock()
        spell.name = "Fireball"
        spell.level = 3
        spell.description = "Big boom"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = None
        return record

    def test_shows_placeholder_by_default(self):
        panel = self._make_panel()
        self.assertTrue(panel._placeholder_label.isVisible())

    def test_show_pending_displays_pending_view(self):
        panel = self._make_panel()
        record = self._make_pending_record()
        panel.show_pending_record(record)
        self.assertFalse(panel._placeholder_label.isVisible())
        self.assertFalse(panel._review_widget.isVisible())
        self.assertTrue(panel._pending_widget.isVisible())

    def test_show_pending_displays_correct_content(self):
        panel = self._make_panel()
        record = self._make_pending_record()
        panel.show_pending_record(record)
        self.assertIn("Sleep", panel._pending_name_label.text())
        self.assertIn("5", panel._pending_order_label.text())
        self.assertIn("100", panel._pending_range_label.text())
        self.assertIn("120", panel._pending_range_label.text())

    def test_show_review_displays_review_editor(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)
        self.assertTrue(panel._review_widget.isVisible())
        self.assertFalse(panel._placeholder_label.isVisible())

    def test_dirty_indicator_hidden_when_not_dirty(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        record.draft_dirty = False
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)
        self.assertFalse(panel._dirty_banner.isVisible())

    def test_dirty_indicator_shown_when_dirty(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        record.draft_dirty = True
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)
        self.assertTrue(panel._dirty_banner.isVisible())

    def test_editing_field_calls_apply_review_edits(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()

        panel._current_record = record
        panel._loading = True
        with patch("app.ui.review_panel.apply_review_edits") as mock_apply:
            panel._field_description.setPlainText("spurious call")
            panel._on_field_edited()
            mock_apply.assert_not_called()

        panel._loading = False
        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)
        with patch("app.ui.review_panel.apply_review_edits") as mock_apply:
            panel._field_name.setText("New Name")
            panel._on_field_edited()
            mock_apply.assert_called_once()
        self.assertTrue(panel._dirty_banner.isVisible())


class TestReviewPanelActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel_with_confirmed_record(self):
        from app.ui.review_panel import ReviewPanel

        config = MagicMock()
        panel = ReviewPanel(config=config)
        record = MagicMock()
        record.spell_id = "abc-123"
        record.status = MagicMock(value="confirmed")
        record.draft_dirty = False
        spell = MagicMock()
        spell.name = "Fireball"
        spell.level = 3
        spell.description = "Big boom"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = spell
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        panel._current_record = record
        panel._current_session = session
        return panel, record, session

    def test_save_blocked_when_duplicate_conflict_exists(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        conflict = MagicMock()
        conflict.canonical_spell.name = "Fireball"
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch(
            "app.ui.review_panel.get_confirmed_save_duplicate_conflict",
            return_value=conflict,
        ), patch("app.ui.review_panel.save_confirmed_changes") as mock_save, patch(
            "app.ui.review_panel.QMessageBox"
        ) as mock_mb:
            panel._on_save_confirmed()
            mock_mb.warning.assert_called_once()
            mock_save.assert_not_called()
        self.assertEqual(emitted, [])

    def test_save_proceeds_when_no_conflict(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch(
            "app.ui.review_panel.get_confirmed_save_duplicate_conflict", return_value=None
        ), patch("app.ui.review_panel.save_confirmed_changes", return_value=record) as mock_save:
            panel._on_save_confirmed()
            mock_save.assert_called_once()
        self.assertEqual(len(emitted), 1)

    def test_discard_calls_discard_and_clears_dirty(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.draft_dirty = True
        panel._dirty_banner.setVisible(True)
        with patch("app.ui.review_panel.discard_record_draft") as mock_discard, patch.object(
            panel, "show_review_record"
        ) as mock_show:
            panel._on_discard()
            mock_discard.assert_called_once_with(record)
            mock_show.assert_called_once_with(panel._current_record, panel._current_session)
        self.assertFalse(panel._dirty_banner.isVisible())

    def test_delete_calls_delete_and_emits_session_changed_on_confirm(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch(
            "app.ui.review_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch("app.ui.review_panel.delete_record", return_value=True) as mock_del:
            panel._on_delete()
            mock_del.assert_called_once_with(session, spell_id="abc-123")
        self.assertGreater(len(emitted), 0)

    def test_delete_aborted_when_user_cancels(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        with patch(
            "app.ui.review_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ), patch("app.ui.review_panel.delete_record") as mock_del:
            panel._on_delete()
            mock_del.assert_not_called()

    def test_reextract_no_op_on_empty_focus_prompt_cancel(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        with patch("app.ui.review_panel.QInputDialog.getText", return_value=("", False)), patch(
            "app.ui.review_panel.reextract_record_into_draft"
        ) as mock_re:
            panel._on_reextract()
            mock_re.assert_not_called()

    def test_reextract_calls_api_when_user_provides_prompt(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        updated_spell = MagicMock()
        updated_spell.name = "Fireball v2"
        updated_spell.level = 3
        updated_spell.description = "Even bigger"
        updated_spell.review_notes = None
        with patch(
            "app.ui.review_panel.QInputDialog.getText", return_value=("focus on damage", True)
        ), patch(
            "app.ui.review_panel.reextract_record_into_draft", return_value=updated_spell
        ) as mock_re, patch("app.ui.review_panel.get_review_draft", return_value=updated_spell):
            panel._on_reextract()
            mock_re.assert_called_once_with(
                session,
                spell_id="abc-123",
                focus_prompt="focus on damage",
                config=panel._config,
            )
            self.assertEqual(panel._field_name.text(), updated_spell.name)

    def test_accept_non_conflicting_record_commits_and_emits_session_changed(self):
        from app.ui.review_panel import DuplicateResolutionStrategy, ReviewPanel

        config = MagicMock()
        panel = ReviewPanel(config=config)
        record = MagicMock()
        record.spell_id = "xyz-789"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = False
        spell = MagicMock()
        spell.name = "Sleep"
        spell.level = 1
        spell.description = "Put targets to sleep"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = None
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record", return_value=True) as mock_accept:
            panel._on_accept()
            mock_accept.assert_called_once_with(
                session,
                spell_id="xyz-789",
                duplicate_resolution=DuplicateResolutionStrategy.SKIP,
                config=config,
            )
        self.assertEqual(len(emitted), 1)

    def test_accept_refreshes_buttons_after_status_changes_to_confirmed(self):
        from app.ui.review_panel import ReviewPanel

        config = MagicMock()
        panel = ReviewPanel(config=config)
        record = MagicMock()
        record.spell_id = "xyz-789"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = False
        spell = MagicMock()
        spell.name = "Sleep"
        spell.level = 1
        spell.description = "Put targets to sleep"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = None
        session = MagicMock()

        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)

        def _accept_side_effect(*args, **kwargs):
            record.status.value = "confirmed"
            return True

        with patch("app.ui.review_panel.accept_review_record", side_effect=_accept_side_effect):
            panel._on_accept()

        self.assertTrue(panel._btn_save.isVisible())
        self.assertFalse(panel._btn_accept.isVisible())

    def test_accept_conflict_skip_leaves_record_uncommitted(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        spell = record.draft_spell
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record", return_value=False), patch(
            "app.ui.review_panel.QDialog"
        ) as mock_dlg_cls, patch("app.ui.review_panel.QVBoxLayout"), patch(
            "app.ui.review_panel.QRadioButton"
        ), patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            panel._on_accept()
        self.assertEqual(emitted, [])

    def test_accept_conflict_dialog_accepted_overwrite_calls_overwrite_strategy(self):
        from app.ui.review_panel import DuplicateResolutionStrategy

        with patch("app.ui.review_panel.accept_review_record") as mock_accept, patch(
            "app.ui.review_panel.QDialog"
        ) as mock_dlg_cls, patch("app.ui.review_panel.QVBoxLayout"), patch(
            "app.ui.review_panel.QRadioButton"
        ), patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.DialogCode = QDialog.DialogCode
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_accept.side_effect = [False, True]
            panel, record, session = self._make_panel_with_confirmed_record()
            record.status = MagicMock(value="needs_review")
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 2)
        self.assertEqual(
            mock_accept.call_args_list[1].kwargs["duplicate_resolution"],
            DuplicateResolutionStrategy.OVERWRITE,
        )

    def test_accept_conflict_dialog_rejected_leaves_record_uncommitted(self):
        with patch("app.ui.review_panel.accept_review_record") as mock_accept, patch(
            "app.ui.review_panel.QDialog"
        ) as mock_dlg_cls, patch("app.ui.review_panel.QVBoxLayout"), patch(
            "app.ui.review_panel.QRadioButton"
        ), patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.DialogCode = QDialog.DialogCode
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            mock_accept.return_value = False
            panel, record, session = self._make_panel_with_confirmed_record()
            record.status = MagicMock(value="needs_review")
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 1)

    def test_accept_conflict_dialog_accepted_calls_accept_review_record_second_time(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        spell = record.draft_spell
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        call_count = [0]

        def mock_accept(*args, **kwargs):
            call_count[0] += 1
            return call_count[0] > 1

        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record", side_effect=mock_accept), patch(
            "app.ui.review_panel.QDialog"
        ) as mock_dlg_cls, patch("app.ui.review_panel.QVBoxLayout"), patch(
            "app.ui.review_panel.QRadioButton"
        ), patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.DialogCode = QDialog.DialogCode
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            panel._on_accept()
        self.assertEqual(call_count[0], 2)
        self.assertGreater(len(emitted), 0)


class TestWorkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def test_detect_worker_emits_spells_detected_on_success(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        routed_doc = MagicMock()
        config = MagicMock()
        result_session = MagicMock()
        r1 = MagicMock()
        r1.status = MagicMock(value="pending_extraction")
        r2 = MagicMock()
        r2.status = MagicMock(value="pending_extraction")
        result_session.records = [r1, r2]

        worker = DetectSpellsWorker(
            routed_document=routed_doc,
            config=config,
            session_state=MagicMock(),
            cancel_event=threading.Event(),
        )
        emitted_counts = []
        worker.spells_detected.connect(lambda n: emitted_counts.append(n))

        with patch("app.ui.workers.detect_spells", return_value=result_session):
            worker.run()

        self.assertEqual(emitted_counts, [2])

    def test_detect_worker_emits_failed_on_exception(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        worker = DetectSpellsWorker(
            routed_document=MagicMock(),
            config=MagicMock(),
            session_state=MagicMock(),
            cancel_event=threading.Event(),
        )
        failures = []
        worker.failed.connect(lambda title, msg: failures.append((title, msg)))

        with patch("app.ui.workers.detect_spells", side_effect=RuntimeError("boom")):
            worker.run()

        self.assertEqual(len(failures), 1)
        self.assertIn("boom", failures[0][1])

    def test_detect_worker_emits_cancelled_when_cancel_set_before_run(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        cancel = threading.Event()
        cancel.set()
        worker = DetectSpellsWorker(
            routed_document=MagicMock(),
            config=MagicMock(),
            session_state=MagicMock(),
            cancel_event=cancel,
        )
        cancelled = []
        worker.cancelled.connect(lambda: cancelled.append(True))

        with patch("app.ui.workers.detect_spells", return_value=MagicMock(records=[])):
            worker.run()

        self.assertEqual(cancelled, [True])

    def test_extract_worker_emits_record_extracted_per_record(self):
        import threading

        from app.ui.workers import ExtractWorker

        r1 = MagicMock()
        r1.spell_id = "id-1"
        r1.status = MagicMock(value="pending_extraction")
        r2 = MagicMock()
        r2.spell_id = "id-2"
        r2.status = MagicMock(value="pending_extraction")
        session = MagicMock()
        session.records = [r1, r2]
        config = MagicMock()

        r1_result = MagicMock()
        r1_result.spell_id = "id-1"
        r1_result.status = MagicMock(value="needs_review")
        r2_result = MagicMock()
        r2_result.spell_id = "id-2"
        r2_result.status = MagicMock(value="needs_review")
        result_session = MagicMock()
        result_session.records = [r1_result, r2_result]

        worker = ExtractWorker(
            session_state=session,
            config=config,
            cancel_event=threading.Event(),
            mode="all",
        )
        extracted = []
        worker.record_extracted.connect(lambda sid: extracted.append(sid))

        with patch("app.ui.workers.extract_all_pending", return_value=result_session):
            worker.run()

        self.assertEqual(sorted(extracted), ["id-1", "id-2"])

    def test_detect_worker_emits_session_ready_with_result(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        result_session = MagicMock()
        result_session.records = []
        worker = DetectSpellsWorker(
            routed_document=MagicMock(),
            config=MagicMock(),
            session_state=MagicMock(),
            cancel_event=threading.Event(),
        )
        sessions = []
        worker.session_ready.connect(lambda s: sessions.append(s))
        with patch("app.ui.workers.detect_spells", return_value=result_session):
            worker.run()
        self.assertEqual(sessions, [result_session])

    def test_extract_worker_emits_extraction_complete_with_result(self):
        import threading

        from app.ui.workers import ExtractWorker

        result_session = MagicMock()
        r1 = MagicMock()
        r1.spell_id = "id-1"
        r1.status = MagicMock(value="pending_extraction")
        result_session.records = [r1]
        session = MagicMock()
        session.records = [r1]

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="all",
        )
        completed = []
        worker.extraction_complete.connect(lambda s: completed.append(s))
        with patch("app.ui.workers.extract_all_pending", return_value=result_session):
            worker.run()
        self.assertEqual(completed, [result_session])

    def test_extract_worker_calls_extract_selected_in_selected_mode(self):
        import threading

        from app.ui.workers import ExtractWorker

        result_session = MagicMock()
        result_session.records = []
        session = MagicMock()
        session.records = []
        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="selected",
        )
        with patch("app.ui.workers.extract_selected_pending", return_value=result_session) as mock_sel, patch(
            "app.ui.workers.extract_all_pending"
        ) as mock_all:
            worker.run()
            mock_sel.assert_called_once()
            mock_all.assert_not_called()

    def test_extract_worker_cancelled_before_start_does_not_call_extract(self):
        import threading

        from app.ui.workers import ExtractWorker

        cancel_event = threading.Event()
        cancel_event.set()
        worker = ExtractWorker(
            session_state=MagicMock(),
            config=MagicMock(),
            cancel_event=cancel_event,
            mode="all",
        )
        with patch("app.ui.workers.extract_all_pending") as mock_extract:
            cancelled_calls = []
            worker.cancelled.connect(lambda: cancelled_calls.append(True))
            worker.run()
        mock_extract.assert_not_called()
        self.assertEqual(cancelled_calls, [True])

    def test_cancel_mid_record_drops_only_inflight_record_deferred(self):
        self.skipTest(
            "Per-record mid-batch cancellation requires streaming callbacks in extraction API."
        )

    def test_extract_worker_cancelled_after_extraction_emits_complete_only(self):
        import threading

        from app.ui.workers import ExtractWorker

        session = MagicMock()
        config = MagicMock()
        cancel_event = threading.Event()
        result_session = MagicMock()
        complete_calls = []
        cancelled_calls = []

        def fake_extract(session_state, *, config):
            cancel_event.set()
            return result_session

        with patch("app.ui.workers.extract_all_pending", side_effect=fake_extract):
            worker = ExtractWorker(
                session_state=session,
                config=config,
                cancel_event=cancel_event,
                mode="all",
            )
            worker.extraction_complete.connect(lambda s: complete_calls.append(s))
            worker.cancelled.connect(lambda: cancelled_calls.append(True))
            worker.run()
        self.assertEqual(complete_calls, [result_session])
        self.assertEqual(cancelled_calls, [])

    def test_detect_worker_forwards_session_state_to_detect_spells(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        session = MagicMock()
        routed = MagicMock()
        config = MagicMock()
        with patch("app.ui.workers.detect_spells") as mock_detect:
            mock_detect.return_value = MagicMock()
            worker = DetectSpellsWorker(
                routed_document=routed,
                config=config,
                session_state=session,
                cancel_event=threading.Event(),
            )
            worker.run()
        mock_detect.assert_called_once_with(routed, config=config, session_state=session)

    def test_detect_worker_cancelled_after_detection_emits_session_ready_only(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        routed = MagicMock()
        session = MagicMock()
        config = MagicMock()
        cancel_event = threading.Event()
        result_session = MagicMock()
        r1 = MagicMock()
        r1.status = MagicMock(value="pending_extraction")
        r2 = MagicMock()
        r2.status = MagicMock(value="pending_extraction")
        result_session.records = [r1, r2]
        ready_calls = []
        cancelled_calls = []

        def fake_detect(routed_doc, *, config, session_state):
            cancel_event.set()
            return result_session

        with patch("app.ui.workers.detect_spells", side_effect=fake_detect):
            worker = DetectSpellsWorker(
                routed_document=routed,
                config=config,
                session_state=session,
                cancel_event=cancel_event,
            )
            worker.session_ready.connect(lambda s: ready_calls.append(s))
            worker.cancelled.connect(lambda: cancelled_calls.append(True))
            worker.run()
        self.assertEqual(ready_calls, [result_session])
        self.assertEqual(cancelled_calls, [])


class TestMainWindowWorkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_window_with_session(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "Player's Handbook"
        win = SpellScribeMainWindow(config=config)
        session = MagicMock()
        session.last_open_path = "/tmp/test.pdf"
        session.records = []
        win._set_session(session, source_path="/tmp/test.pdf")
        win._routed_document = MagicMock()
        return win

    def test_extraction_actions_disabled_when_detect_spells_started(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.DetectSpellsWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker
            win._on_detect_spells()
            self.assertTrue(win._worker_running)
            self.assertFalse(win._action_detect.isEnabled())
            self.assertFalse(win._action_extract_all.isEnabled())
        self.assertFalse(win._action_extract_selected.isEnabled())

    def test_cancel_sets_cancel_event(self):
        import threading

        win = self._make_window_with_session()
        cancel_event = threading.Event()
        win._cancel_event = cancel_event
        win._on_cancel()
        self.assertTrue(cancel_event.is_set())

    def test_status_bar_updates_on_spells_detected(self):
        win = self._make_window_with_session()
        mock_panel = MagicMock()
        win._spell_list_panel = mock_panel
        win._on_spells_detected(7)
        self.assertIn("7", win._status_bar.currentMessage())
        mock_panel.refresh.assert_called_once_with(win._session)

    def test_extraction_actions_disabled_while_worker_active(self):
        win = self._make_window_with_session()
        win._worker_running = True
        win._update_action_states()
        self.assertFalse(win._action_detect.isEnabled())
        self.assertFalse(win._action_extract_all.isEnabled())
        self.assertTrue(win._action_cancel.isEnabled())

    def test_extraction_actions_re_enabled_after_extraction_complete_signal(self):
        win = self._make_window_with_session()
        win._worker_running = True
        win._update_action_states()
        updated_session = MagicMock()
        updated_session.records = []
        updated_session.last_open_path = "/tmp/test.pdf"
        win._on_extraction_complete(updated_session)
        self.assertFalse(win._worker_running)
        self.assertTrue(win._action_detect.isEnabled())
        self.assertFalse(win._action_cancel.isEnabled())

    def test_extract_selected_passes_selected_mode_to_worker(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker
            win._on_extract_selected()
            _, kwargs = mock_worker_cls.call_args
            self.assertEqual(kwargs.get("mode"), "selected")

    def test_extraction_complete_refreshes_spell_list(self):
        win = self._make_window_with_session()
        mock_panel = MagicMock()
        win._spell_list_panel = mock_panel
        updated_session = MagicMock()
        updated_session.records = []
        updated_session.last_open_path = "/tmp/test.pdf"
        win._on_extraction_complete(updated_session)
        mock_panel.refresh.assert_called_once_with(updated_session)

    def test_settings_action_disabled_when_worker_running(self):
        win = self._make_window_with_session()
        win._worker_running = True
        win._update_action_states()
        self.assertFalse(win._action_settings.isEnabled())

    def test_extraction_complete_updates_status_bar(self):
        win = self._make_window_with_session()
        updated_session = MagicMock()
        updated_session.records = []
        win._on_extraction_complete(updated_session)
        self.assertNotEqual(win._status_bar.currentMessage(), "")


class TestDocumentOpenFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_window(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "Player's Handbook"
        config.document_names_by_sha256 = {}
        config.document_offsets = {}
        config.force_ocr_by_sha256 = {}
        return SpellScribeMainWindow(config=config)

    def test_same_sha_reopen_refreshes_display_path_only(self):
        win = self._make_window()
        existing_session = MagicMock()
        existing_session.source_sha256_hex = "a" * 64
        existing_session.last_open_path = "/old/path.pdf"
        existing_session.records = []
        win._session = existing_session

        same_path = "/new/same-file.pdf"
        with patch("app.ui.main_window.compute_sha256_hex", return_value="a" * 64), patch(
            "app.ui.main_window.route_document"
        ) as mock_route, patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=existing_session
        ):
            routed = MagicMock()
            routed.coordinate_map = CoordinateAwareTextMap(lines=[])
            mock_route.return_value = routed
            win._open_document(same_path)

        self.assertIn("same-file.pdf", win.windowTitle())
        self.assertIn(Path(same_path).name, win._status_bar.currentMessage())
        self.assertIs(win._session, existing_session)
        self.assertEqual(win._session.last_open_path, same_path)

    def test_identity_dialog_abort_leaves_session_unchanged(self):
        win = self._make_window()
        original_session = MagicMock()
        original_session.source_sha256_hex = "a" * 64
        win._session = original_session

        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Rejected
            win._open_document("/some/new-file.pdf")
            mock_route.assert_not_called()

        self.assertIs(win._session, original_session)

    def test_different_sha_prompt_has_three_choices(self):
        win = self._make_window()
        existing = MagicMock()
        existing.source_sha256_hex = "a" * 64
        confirmed_record = MagicMock()
        confirmed_record.status = MagicMock(value="confirmed")
        existing.records = [confirmed_record]
        win._session = existing
        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.QMessageBox") as mock_mb:
            mock_box = MagicMock()
            mock_mb.return_value = mock_box
            mock_box.clickedButton.return_value = MagicMock()
            mock_box.addButton.return_value = MagicMock()
            win._open_document("/new/file.pdf")
            mock_box.exec.assert_called_once()

    def test_different_sha_replaces_silently_with_only_pending_records(self):
        win = self._make_window()
        existing_session = MagicMock()
        existing_session.source_sha256_hex = "a" * 64
        pending_record = MagicMock()
        pending_record.status = MagicMock(value="pending_extraction")
        existing_session.records = [pending_record]
        win._session = existing_session
        with patch("app.ui.main_window.compute_sha256_hex", return_value="c" * 64), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.QMessageBox") as mock_mb, patch(
            "app.ui.main_window.DocumentIdentityDialog"
        ) as mock_dlg_cls, patch("app.ui.main_window.route_document") as mock_route:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = MagicMock()
            mock_routed = MagicMock()
            mock_routed.coordinate_map = CoordinateAwareTextMap(lines=[])
            mock_route.return_value = mock_routed
            win._open_document("/new/file.pdf")
            mock_mb.question.assert_not_called()

    def test_open_file_dialog_uses_last_import_directory(self):
        win = self._make_window()
        win._config.last_import_directory = "/my/docs"
        with patch("app.ui.main_window.QFileDialog.getOpenFileName", return_value=("", "")) as mock_dlg:
            win._on_open_file()
            args, kwargs = mock_dlg.call_args
            dir_arg = args[2] if len(args) > 2 else kwargs.get("dir", "")
            self.assertEqual(Path(dir_arg), Path("/my/docs"))

    def test_export_choice_aborts_open_and_preserves_session(self):
        win = self._make_window()
        existing = MagicMock()
        existing.source_sha256_hex = "a" * 64
        confirmed_record = MagicMock()
        confirmed_record.status = MagicMock(value="confirmed")
        existing.records = [confirmed_record]
        win._session = existing
        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ):
            box = MagicMock()
            export_btn = MagicMock()
            discard_btn = MagicMock()
            cancel_btn = MagicMock()
            with patch("app.ui.main_window.QMessageBox", return_value=box):
                box.addButton.side_effect = [export_btn, discard_btn, cancel_btn]
                box.clickedButton.return_value = export_btn
                win._open_document("/new/file.pdf")
            self.assertIs(win._session, existing)

    def test_different_sha_discard_replaces_session(self):
        win = self._make_window()
        win._session = MagicMock()
        confirmed_record = MagicMock()
        confirmed_record.status = MagicMock(value="confirmed")
        win._session.records = [confirmed_record]
        new_path = "/new/doc.pdf"
        new_sha = "deadbeef" * 8
        new_routed = MagicMock()
        new_routed.coordinate_map = CoordinateAwareTextMap(lines=[])
        discard_btn = MagicMock()
        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.route_document", return_value=new_routed
        ), patch("app.ui.main_window.restore_session_state_for_source", return_value=None), patch(
            "app.ui.main_window.DocumentIdentityDialog"
        ) as mock_id_dlg, patch("app.ui.main_window.QMessageBox") as mock_mb:
            mock_id_dlg.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_id_dlg.return_value.get_result.return_value = MagicMock(
                source_display_name="PHB",
                page_offset=0,
                force_ocr=False,
            )
            box = MagicMock()
            mock_mb.return_value = box
            box.exec.return_value = 0
            export_btn = MagicMock()
            cancel_btn = MagicMock()
            box.addButton.side_effect = [export_btn, discard_btn, cancel_btn]
            box.clickedButton.return_value = discard_btn
            win._open_document(new_path)
        self.assertEqual(win._session.source_sha256_hex, new_sha)

    def test_different_sha_export_then_replace_deferred(self):
        self.skipTest("Export not implemented in this change; deferred.")


class TestIdentityDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def test_dialog_pre_fills_document_name_from_config(self):
        from app.ui.identity_dialog import DocumentIdentityDialog

        dlg = DocumentIdentityDialog(
            sha256_hex="a" * 64,
            default_document_name="Player's Handbook",
        )
        self.assertEqual(dlg._name_edit.text(), "Player's Handbook")

    def test_accepted_dialog_returns_document_identity_input(self):
        from app.pipeline.identity import DocumentIdentityInput
        from app.ui.identity_dialog import DocumentIdentityDialog

        dlg = DocumentIdentityDialog(
            sha256_hex="a" * 64,
            default_document_name="PHB",
        )
        dlg._name_edit.setText("Monster Manual")
        dlg._offset_spin.setValue(10)
        result = dlg.get_result()
        self.assertIsInstance(result, DocumentIdentityInput)
        self.assertEqual(result.source_display_name, "Monster Manual")
        self.assertEqual(result.page_offset, 10)


class TestMainWindowPanelWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_window_with_panels(self):
        from app.ui.main_window import SpellScribeMainWindow

        config = MagicMock()
        config.default_source_document = "PHB"
        config.custom_schools = []
        config.custom_spheres = []
        config.document_names_by_sha256 = {}
        config.document_offsets = {}
        config.force_ocr_by_sha256 = {}
        return SpellScribeMainWindow(config=config)

    def test_panels_created_after_construction(self):
        from app.ui.document_panel import DocumentPanel
        from app.ui.review_panel import ReviewPanel
        from app.ui.spell_list_panel import SpellListPanel

        win = self._make_window_with_panels()
        self.assertIsNotNone(win.findChild(DocumentPanel))
        self.assertIsNotNone(win.findChild(SpellListPanel))
        self.assertIsNotNone(win.findChild(ReviewPanel))

    def test_spell_selection_routes_pending_to_review_panel(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "p1"
        pending_record.status = MagicMock(value="pending_extraction")
        pending_record.boundary_end_line = 50
        pending_record.boundary_start_line = 10
        pending_record.extraction_order = 1
        pending_record.draft_spell = None
        pending_record.canonical_spell = None
        session = MagicMock()
        session.records = [pending_record]
        session.source_sha256_hex = "a" * 64
        session.last_open_path = "/test.pdf"
        session.coordinate_map = MagicMock()
        session.coordinate_map.regions_for_range.return_value = []
        session.model_copy.return_value = session
        win._session = session
        win._routed_document = MagicMock()
        with patch.object(win._review_panel, "show_pending_record") as mock_pending:
            win._on_spell_selected("p1")
            mock_pending.assert_called_once_with(pending_record)

    def test_spell_selection_routes_confirmed_to_review_panel(self):
        win = self._make_window_with_panels()
        confirmed_record = MagicMock()
        confirmed_record.spell_id = "c1"
        confirmed_record.status = MagicMock(value="confirmed")
        confirmed_record.boundary_start_line = 0
        confirmed_record.boundary_end_line = -1
        session = MagicMock()
        session.records = [confirmed_record]
        session.selected_spell_id = confirmed_record.spell_id
        session.model_copy.return_value = session
        session.coordinate_map = MagicMock()
        session.coordinate_map.regions_for_range.return_value = []
        win._session = session
        win._routed_document = MagicMock()
        with patch.object(win._review_panel, "show_review_record") as mock_show:
            win._on_spell_selected(confirmed_record.spell_id)
            mock_show.assert_called_once_with(confirmed_record, win._session)

    def test_document_panel_shows_placeholder_at_startup(self):
        from app.ui.document_panel import DocumentPanel

        win = self._make_window_with_panels()
        doc_panel = win.findChild(DocumentPanel)
        self.assertIs(doc_panel._stack.currentWidget(), doc_panel._placeholder_label)

    def test_spell_list_panel_starts_with_empty_sections(self):
        from app.ui.spell_list_panel import SpellListPanel

        win = self._make_window_with_panels()
        spell_panel = win.findChild(SpellListPanel)
        total = (
            spell_panel._confirmed_list.count()
            + spell_panel._needs_review_list.count()
            + spell_panel._pending_list.count()
        )
        self.assertEqual(total, 0)

    def test_set_session_calls_spell_list_refresh(self):
        win = self._make_window_with_panels()
        new_session = MagicMock()
        win._spell_list_panel = MagicMock()
        win._set_session(new_session, source_path="test.pdf")
        win._spell_list_panel.refresh.assert_called_once_with(new_session)

    def test_spell_selection_updates_session_selected_id(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "spell-42"
        pending_record.status = MagicMock(value="pending_extraction")
        pending_record.boundary_start_line = 0
        pending_record.boundary_end_line = -1
        session = MagicMock()
        session.records = [pending_record]
        session.selected_spell_id = None
        session.coordinate_map = MagicMock()
        session.coordinate_map.regions_for_range.return_value = []
        win._session = session
        win._routed_document = MagicMock()
        with patch.object(win._review_panel, "show_pending_record"):
            win._on_spell_selected("spell-42")
        self.assertEqual(session.selected_spell_id, "spell-42")

    def test_spell_selection_dispatches_pdf_to_doc_panel(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "spell-55"
        pending_record.status = MagicMock(value="pending_extraction")
        pending_record.boundary_start_line = 0
        pending_record.boundary_end_line = 5
        region = MagicMock()
        region.page = 1
        region.bbox = (0.0, 0.0, 100.0, 50.0)
        session = MagicMock()
        session.records = [pending_record]
        session.coordinate_map.regions_for_range.return_value = [region]
        session.last_open_path = "test.pdf"
        session.selected_spell_id = None
        session.model_copy.return_value = session
        win._session = session
        win._routed_document = MagicMock()
        with patch("app.ui.main_window.fitz") as mock_fitz, patch.object(
            win._doc_panel, "display_pdf_page"
        ) as mock_display:
            mock_fitz.open.return_value.__enter__ = MagicMock(
                return_value=mock_fitz.open.return_value
            )
            mock_fitz.open.return_value.__exit__ = MagicMock(return_value=False)
            win._on_spell_selected("spell-55")
        mock_display.assert_called_once()

    def test_spell_selection_shows_placeholder_when_pdf_open_fails(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "spell-56"
        pending_record.status = MagicMock(value="pending_extraction")
        pending_record.boundary_start_line = 0
        pending_record.boundary_end_line = 5
        region = MagicMock()
        region.page = 0
        region.bbox = (0.0, 0.0, 100.0, 50.0)
        session = MagicMock()
        session.records = [pending_record]
        session.coordinate_map.regions_for_range.return_value = [region]
        session.last_open_path = "missing.pdf"
        session.selected_spell_id = None
        win._session = session
        win._routed_document = MagicMock()

        with patch("app.ui.main_window.fitz.open", side_effect=RuntimeError("cannot open")), patch.object(
            win._doc_panel, "show_placeholder"
        ) as mock_placeholder:
            win._on_spell_selected("spell-56")

        mock_placeholder.assert_called_once()

    def test_spell_selection_shows_placeholder_when_routed_document_missing_for_pdf(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "spell-57"
        pending_record.status = MagicMock(value="pending_extraction")
        pending_record.boundary_start_line = 0
        pending_record.boundary_end_line = 5
        region = MagicMock()
        region.page = 0
        region.bbox = (0.0, 0.0, 100.0, 50.0)
        session = MagicMock()
        session.records = [pending_record]
        session.coordinate_map.regions_for_range.return_value = [region]
        session.last_open_path = "test.pdf"
        session.selected_spell_id = None
        win._session = session
        win._routed_document = None

        with patch.object(win._doc_panel, "show_placeholder") as mock_placeholder:
            win._on_spell_selected("spell-57")

        mock_placeholder.assert_called_once()
