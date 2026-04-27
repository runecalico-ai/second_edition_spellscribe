"""Tests for SpellScribeMainWindow shell and toolbar."""
from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolBar

from app.models import CoordinateAwareTextMap
from app.pipeline.identity import DocumentIdentityMetadata
from app.pipeline.ingestion import RoutedDocument
from app.session import SpellRecordStatus

# Deferred import so QApplication is created before widgets
_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@dataclass(slots=True)
class _SpellListFixtureSpell:
    name: str


@dataclass(slots=True)
class _SpellListFixtureRecord:
    spell_id: str
    status: SpellRecordStatus
    canonical_spell: _SpellListFixtureSpell | None
    draft_spell: _SpellListFixtureSpell | None
    section_order: int


@dataclass(slots=True)
class _SpellListFixtureSession:
    records: list[_SpellListFixtureRecord]
    selected_spell_id: str | None = None


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
        return _SpellListFixtureSession(records=records)

    def _make_record(self, spell_id, status_value, name="Magic Missile", section_order=0):
        status = SpellRecordStatus(status_value)
        spell = _SpellListFixtureSpell(name=name)

        if status == SpellRecordStatus.CONFIRMED:
            canonical_spell = spell
            draft_spell = spell
        elif status == SpellRecordStatus.NEEDS_REVIEW:
            canonical_spell = None
            draft_spell = spell
        else:
            canonical_spell = None
            draft_spell = None

        return _SpellListFixtureRecord(
            spell_id=spell_id,
            status=status,
            canonical_spell=canonical_spell,
            draft_spell=draft_spell,
            section_order=section_order,
        )

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
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._confirmed_list.count(), 1)
        self.assertIn("Fireball", panel._confirmed_list.item(0).text())

    def test_refresh_populates_needs_review_section(self):
        panel = self._make_panel()
        r = self._make_record("id-2", "needs_review", "Sleep")
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._needs_review_list.count(), 1)

    def test_refresh_populates_pending_section(self):
        panel = self._make_panel()
        r = self._make_record("id-3", "pending_extraction", "Unknown")
        session = self._make_session([r])
        panel.refresh(session)
        self.assertEqual(panel._pending_list.count(), 1)

    def test_selection_emits_spell_id_signal(self):
        panel = self._make_panel()
        r = self._make_record("id-1", "confirmed", "Fireball")
        session = self._make_session([r])
        panel.refresh(session)

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))
        panel._confirmed_list.setCurrentRow(0)
        self.assertEqual(emitted, ["id-1"])

    def test_clearing_last_selection_emits_empty_spell_id_signal(self):
        panel = self._make_panel()
        r = self._make_record("id-1", "confirmed", "Fireball")
        session = self._make_session([r])
        panel.refresh(session)

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))

        panel._confirmed_list.setCurrentRow(0)
        panel._confirmed_list.clearSelection()

        self.assertEqual(emitted, ["id-1", ""])

    def test_switching_lists_does_not_emit_empty_spell_id_signal(self):
        panel = self._make_panel()
        confirmed = self._make_record("id-confirmed", "confirmed", "Fireball")
        needs_review = self._make_record("id-review", "needs_review", "Sleep")

        panel.refresh(self._make_session([confirmed, needs_review]))

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))

        panel._confirmed_list.setCurrentRow(0)
        panel._needs_review_list.setCurrentRow(0)

        self.assertEqual(emitted, ["id-confirmed", "id-review"])
        self.assertNotIn("", emitted)

    def test_refresh_preserves_selection_when_spell_still_exists(self):
        panel = self._make_panel()
        confirmed = self._make_record("id-confirmed", "confirmed", "Fireball")

        panel.refresh(self._make_session([confirmed]))

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))

        panel._confirmed_list.setCurrentRow(0)
        self.assertEqual(len(panel._confirmed_list.selectedItems()), 1)

        panel.refresh(self._make_session([confirmed]))

        total_selected = (
            len(panel._confirmed_list.selectedItems())
            + len(panel._needs_review_list.selectedItems())
            + len(panel._pending_list.selectedItems())
        )
        self.assertEqual(total_selected, 1)
        self.assertEqual(
            panel._confirmed_list.selectedItems()[0].data(Qt.ItemDataRole.UserRole),
            "id-confirmed",
        )
        self.assertEqual(emitted, ["id-confirmed"])

    def test_refresh_emits_empty_when_selected_spell_is_removed(self):
        panel = self._make_panel()
        confirmed = self._make_record("id-confirmed", "confirmed", "Fireball")

        panel.refresh(self._make_session([confirmed]))

        emitted = []
        panel.selected_spell_id_changed.connect(lambda sid: emitted.append(sid))

        panel._confirmed_list.setCurrentRow(0)
        self.assertEqual(len(panel._confirmed_list.selectedItems()), 1)

        panel.refresh(self._make_session([]))

        total_selected = (
            len(panel._confirmed_list.selectedItems())
            + len(panel._needs_review_list.selectedItems())
            + len(panel._pending_list.selectedItems())
        )
        self.assertEqual(total_selected, 0)
        self.assertEqual(emitted, ["id-confirmed", ""])

    def test_refresh_sorts_by_section_order_within_status_bucket(self):
        panel = self._make_panel()
        first = self._make_record("id-1", "confirmed", "First", section_order=1)
        second = self._make_record("id-2", "confirmed", "Second", section_order=2)
        pending_first = self._make_record(
            "12345678-aaa", "pending_extraction", section_order=3
        )
        pending_second = self._make_record(
            "abcdef12-bbb", "pending_extraction", section_order=4
        )

        session = self._make_session([second, pending_second, first, pending_first])
        panel.refresh(session)

        self.assertEqual(panel._confirmed_list.item(0).text(), "First")
        self.assertEqual(panel._confirmed_list.item(1).text(), "Second")
        self.assertEqual(panel._pending_list.item(0).text(), "[Pending] 12345678")
        self.assertEqual(panel._pending_list.item(1).text(), "[Pending] abcdef12")

    def test_items_store_spell_id_in_user_role(self):
        panel = self._make_panel()
        confirmed = self._make_record("id-confirmed", "confirmed", "Fireball")
        needs_review = self._make_record("id-review", "needs_review", "Sleep")
        pending = self._make_record("1234567890ab", "pending_extraction")

        panel.refresh(self._make_session([confirmed, needs_review, pending]))

        self.assertEqual(
            panel._confirmed_list.item(0).data(Qt.ItemDataRole.UserRole), "id-confirmed"
        )
        self.assertEqual(
            panel._needs_review_list.item(0).data(Qt.ItemDataRole.UserRole), "id-review"
        )
        self.assertEqual(
            panel._pending_list.item(0).data(Qt.ItemDataRole.UserRole), "1234567890ab"
        )

    def test_selecting_one_list_clears_selection_in_other_lists(self):
        panel = self._make_panel()
        confirmed = self._make_record("id-confirmed", "confirmed", "Fireball")
        needs_review = self._make_record("id-review", "needs_review", "Sleep")
        pending = self._make_record("pending-1", "pending_extraction")

        panel.refresh(self._make_session([confirmed, needs_review, pending]))

        panel._confirmed_list.setCurrentRow(0)
        self.assertEqual(len(panel._confirmed_list.selectedItems()), 1)

        panel._needs_review_list.setCurrentRow(0)
        self.assertEqual(len(panel._confirmed_list.selectedItems()), 0)
        self.assertEqual(len(panel._needs_review_list.selectedItems()), 1)
        self.assertEqual(len(panel._pending_list.selectedItems()), 0)

    def test_display_labels_prefer_draft_then_canonical_or_pending_prefix(self):
        panel = self._make_panel()

        confirmed_prefers_draft = self._make_record(
            "id-confirmed", "confirmed", "Canonical Name", section_order=0
        )
        confirmed_prefers_draft.draft_spell = _SpellListFixtureSpell(name="Draft Name")

        needs_review_prefers_draft = self._make_record(
            "id-review", "needs_review", "Needs Review Draft", section_order=0
        )
        needs_review_prefers_draft.canonical_spell = _SpellListFixtureSpell(
            name="Needs Review Canonical"
        )

        confirmed_fallback_canonical = self._make_record(
            "id-confirmed-fallback", "confirmed", "Canonical Fallback", section_order=1
        )
        confirmed_fallback_canonical.draft_spell = None

        pending = self._make_record("abcdef123456", "pending_extraction")

        panel.refresh(
            self._make_session(
                [
                    confirmed_prefers_draft,
                    needs_review_prefers_draft,
                    confirmed_fallback_canonical,
                    pending,
                ]
            )
        )

        self.assertEqual(panel._confirmed_list.item(0).text(), "Draft Name")
        self.assertEqual(panel._needs_review_list.item(0).text(), "Needs Review Draft")
        self.assertEqual(panel._confirmed_list.item(1).text(), "Canonical Fallback")
        self.assertEqual(panel._pending_list.item(0).text(), "[Pending] abcdef12")

        self.assertNotEqual(panel._confirmed_list.item(0).text(), "Canonical Name")
        self.assertNotEqual(panel._needs_review_list.item(0).text(), "Needs Review Canonical")


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
        self.assertEqual(panel._stack.count(), 3)
        self.assertIs(panel._stack.currentWidget(), panel._placeholder_label)
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
        self.assertEqual(panel._pending_name_label.text(), "Spell: Sleep")
        self.assertEqual(panel._pending_order_label.text(), "Extraction order: 5")
        self.assertEqual(panel._pending_range_label.text(), "Boundary lines: 100-120")

    def test_show_review_displays_review_editor(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)
        self.assertTrue(panel._review_widget.isVisible())
        self.assertFalse(panel._placeholder_label.isVisible())

    def test_show_review_unrecoverable_record_falls_back_to_placeholder(self):
        panel = self._make_panel()
        record = MagicMock()
        record.spell_id = "broken-1"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = False
        record.draft_spell = None
        record.canonical_spell = None
        session = MagicMock()

        panel.show_review_record(record, session)

        self.assertIs(panel._stack.currentWidget(), panel._placeholder_label)
        self.assertFalse(panel._loading)

    def test_show_review_seeds_fields_from_get_review_draft(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()

        draft = MagicMock()
        draft.name = "Magic Missile"
        draft.level = 1
        draft.description = "A dart of force"
        draft.class_list = "Wizard"
        draft.school = ["Evocation"]
        draft.sphere = None
        draft.range = "60 yds"
        draft.casting_time = "1"
        draft.duration = "Special"
        draft.area_of_effect = "One target"
        draft.saving_throw = "None"
        draft.components = ["V", "S"]
        draft.reversible = False
        draft.needs_review = True
        draft.review_notes = "Check source wording"

        with patch("app.ui.review_panel.get_review_draft", return_value=draft):
            panel.show_review_record(record, session)

        self.assertEqual(panel._field_name.text(), "Magic Missile")
        self.assertEqual(panel._field_level.text(), "1")
        self.assertEqual(panel._field_description.toPlainText(), "A dart of force")
        self.assertEqual(panel._field_class_list.currentText(), "Wizard")
        self.assertEqual(panel._field_school.text(), "Evocation")
        self.assertEqual(panel._field_sphere.text(), "")
        self.assertEqual(panel._field_range.text(), "60 yds")
        self.assertEqual(panel._field_casting_time.text(), "1")
        self.assertEqual(panel._field_duration.text(), "Special")
        self.assertEqual(panel._field_area_of_effect.text(), "One target")
        self.assertEqual(panel._field_saving_throw.text(), "None")
        self.assertEqual(panel._field_components.text(), "V, S")
        self.assertFalse(panel._field_reversible.isChecked())
        self.assertTrue(panel._field_needs_review.isChecked())
        self.assertEqual(panel._field_review_notes.toPlainText(), "Check source wording")

    def test_show_review_resets_loading_when_seeding_raises(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()

        class _ExplodingDraft:
            @property
            def name(self):
                raise RuntimeError("seed failed")

        with patch("app.ui.review_panel.get_review_draft", return_value=_ExplodingDraft()):
            with self.assertRaisesRegex(RuntimeError, "seed failed"):
                panel.show_review_record(record, session)

        self.assertFalse(panel._loading)

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
            self.assertEqual(mock_apply.call_args.kwargs["draft_updates"]["name"], "New Name")
            self.assertEqual(mock_apply.call_args.kwargs["draft_updates"]["level"], "3")
            self.assertIsNone(mock_apply.call_args.kwargs["draft_updates"]["sphere"])
        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertEqual(panel._dirty_banner.text(), "Unsaved changes")

    def test_wizard_empty_sphere_edit_stays_valid(self):
        from app.models import ClassList, Component, Spell
        from app.session import SpellRecord

        panel = self._make_panel()
        session = MagicMock()

        spell = Spell(
            name="Sleep",
            class_list=ClassList.WIZARD,
            level=1,
            school=["Enchantment/Charm"],
            sphere=None,
            range="30 yds",
            components=[Component.V, Component.S],
            duration="5 rounds",
            casting_time="1",
            area_of_effect="30-ft cube",
            saving_throw="Neg.",
            description="Puts creatures to sleep.",
            source_document="PHB",
            extraction_start_line=1,
            extraction_end_line=2,
        )
        record = SpellRecord(
            spell_id="wiz-empty-sphere",
            status=SpellRecordStatus.NEEDS_REVIEW,
            extraction_order=0,
            section_order=0,
            boundary_start_line=0,
            draft_spell=spell,
        )

        panel.show_review_record(record, session)
        panel._field_name.setText("Sleep II")
        panel._field_sphere.setText("")
        panel._on_field_edited()

        self.assertIsNotNone(record.draft_spell)
        self.assertIsNone(record.draft_spell.sphere)
        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertEqual(panel._dirty_banner.text(), "Unsaved changes")

    def test_priest_sphere_payload_remains_list_based(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()

        draft = MagicMock()
        draft.name = "Bless"
        draft.level = 1
        draft.description = "Priest support spell"
        draft.class_list = "Priest"
        draft.school = ["Abjuration"]
        draft.sphere = ["Combat"]
        draft.range = "60 yds"
        draft.casting_time = "1"
        draft.duration = "6 rounds"
        draft.area_of_effect = "50-ft radius"
        draft.saving_throw = "None"
        draft.components = ["V", "S"]
        draft.reversible = False
        draft.needs_review = True
        draft.review_notes = None

        with patch("app.ui.review_panel.get_review_draft", return_value=draft):
            panel.show_review_record(record, session)

        with patch("app.ui.review_panel.apply_review_edits") as mock_apply:
            panel._field_sphere.setText("Combat, Healing")
            panel._on_field_edited()
            self.assertEqual(mock_apply.call_args.kwargs["draft_updates"]["class_list"], "Priest")
            self.assertEqual(
                mock_apply.call_args.kwargs["draft_updates"]["sphere"],
                ["Combat", "Healing"],
            )

        with patch("app.ui.review_panel.apply_review_edits") as mock_apply:
            panel._field_sphere.setText("")
            panel._on_field_edited()
            self.assertEqual(mock_apply.call_args.kwargs["draft_updates"]["sphere"], [])

    def test_invalid_edit_shows_invalid_banner(self):
        panel = self._make_panel()
        record = self._make_needs_review_record()
        session = MagicMock()

        with patch("app.ui.review_panel.get_review_draft", return_value=record.draft_spell):
            panel.show_review_record(record, session)

        with patch(
            "app.ui.review_panel.apply_review_edits",
            side_effect=ValueError("bad level"),
        ):
            panel._field_level.setText("not-an-int")
            panel._on_field_edited()

        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertIn("Invalid: bad level", panel._dirty_banner.text())


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

    def _make_panel_with_needs_review_record(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        spell = record.draft_spell
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        return panel, record, session

    def _make_panel_with_draft_only_needs_review_record(self):
        from app.ui.review_panel import ReviewPanel

        config = MagicMock()
        panel = ReviewPanel(config=config)
        record = MagicMock()
        record.spell_id = "needs-review-1"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = False

        spell = MagicMock()
        spell.name = "Sleep"
        spell.level = 1
        spell.description = "Puts targets to sleep"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = None

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

    def test_save_shows_critical_and_does_not_emit_when_backend_raises(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.get_confirmed_save_duplicate_conflict", return_value=None
        ), patch(
            "app.ui.review_panel.save_confirmed_changes",
            side_effect=RuntimeError("database unavailable"),
        ) as mock_save, patch("app.ui.review_panel.QMessageBox.critical") as mock_critical:
            panel._on_save_confirmed()
            mock_save.assert_called_once()
            mock_critical.assert_called_once()
            self.assertNotIn("database unavailable", mock_critical.call_args.args[2])

        self.assertEqual(emitted, [])

    def test_save_blocked_when_form_is_currently_invalid(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.apply_review_edits",
            side_effect=ValueError("bad level"),
        ):
            panel._field_level.setText("not-an-int")
            panel._on_field_edited()

        with patch("app.ui.review_panel.QMessageBox.warning") as mock_warning, patch(
            "app.ui.review_panel.get_confirmed_save_duplicate_conflict", return_value=None
        ) as mock_conflict, patch("app.ui.review_panel.save_confirmed_changes") as mock_save:
            panel._on_save_confirmed()

        mock_warning.assert_called_once()
        self.assertIn("validation errors", mock_warning.call_args.args[2].lower())
        mock_conflict.assert_not_called()
        mock_save.assert_not_called()
        self.assertEqual(emitted, [])

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

    def test_discard_shows_critical_and_does_not_emit_when_backend_raises(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.draft_dirty = True
        panel._dirty_banner.setVisible(True)
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.discard_record_draft",
            side_effect=RuntimeError("database unavailable"),
        ) as mock_discard, patch(
            "app.ui.review_panel.QMessageBox.critical"
        ) as mock_critical, patch.object(panel, "show_review_record") as mock_show:
            panel._on_discard()
            mock_discard.assert_called_once_with(record)
            mock_critical.assert_called_once()
            self.assertNotIn("database unavailable", mock_critical.call_args.args[2])
            mock_show.assert_not_called()

        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertEqual(emitted, [])

    def test_discard_enabled_for_needs_review_with_canonical_spell(self):
        panel, record, session = self._make_panel_with_needs_review_record()
        self.assertIsNotNone(record.canonical_spell)
        self.assertTrue(panel._btn_discard.isEnabled())
        self.assertEqual(panel._btn_discard.toolTip(), "")

    def test_discard_needs_review_without_canonical_shows_warning_and_keeps_draft(self):
        from app.ui.review_panel import ReviewPanel

        config = MagicMock()
        panel = ReviewPanel(config=config)
        record = MagicMock()
        record.spell_id = "needs-review-1"
        record.status = MagicMock(value="needs_review")
        record.draft_dirty = True

        spell = MagicMock()
        spell.name = "Sleep"
        spell.level = 1
        spell.description = "Puts targets to sleep"
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = None

        session = MagicMock()
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)

        self.assertFalse(panel._btn_discard.isEnabled())
        self.assertIn("draft-only Needs Review", panel._btn_discard.toolTip())
        self.assertFalse(panel._btn_reextract.isEnabled())
        self.assertIn("draft-only Needs Review", panel._btn_reextract.toolTip())

        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch("app.ui.review_panel.discard_record_draft") as mock_discard, patch(
            "app.ui.review_panel.QMessageBox.warning"
        ) as mock_warning:
            panel._on_discard()

        mock_warning.assert_called_once_with(
            panel,
            "Discard Unavailable",
            "Discard is unavailable for draft-only Needs Review records. "
            "Use Delete instead.",
        )
        mock_discard.assert_not_called()
        self.assertIs(panel._stack.currentWidget(), panel._review_widget)
        self.assertEqual(panel._field_name.text(), "Sleep")
        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertIs(record.draft_spell, spell)
        self.assertEqual(emitted, [])

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
        self.assertEqual(emitted, [session])
        self.assertIsNone(panel._current_record)
        self.assertIs(panel._stack.currentWidget(), panel._placeholder_label)

    def test_delete_shows_error_and_keeps_current_record_when_delete_fails(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch(
            "app.ui.review_panel.delete_record", return_value=False
        ) as mock_del, patch("app.ui.review_panel.QMessageBox.warning") as mock_warning:
            panel._on_delete()
            mock_del.assert_called_once_with(session, spell_id="abc-123")
            mock_warning.assert_called_once()

        self.assertIs(panel._current_record, record)
        self.assertIs(panel._stack.currentWidget(), panel._review_widget)
        self.assertEqual(emitted, [])

    def test_delete_shows_critical_and_keeps_current_record_when_backend_raises(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch(
            "app.ui.review_panel.delete_record",
            side_effect=RuntimeError("database unavailable"),
        ) as mock_del, patch("app.ui.review_panel.QMessageBox.critical") as mock_critical:
            panel._on_delete()
            mock_del.assert_called_once_with(session, spell_id="abc-123")
            mock_critical.assert_called_once()
            self.assertNotIn("database unavailable", mock_critical.call_args.args[2])

        self.assertIs(panel._current_record, record)
        self.assertIs(panel._stack.currentWidget(), panel._review_widget)
        self.assertEqual(emitted, [])

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
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.QInputDialog.getText", return_value=("", False)), patch(
            "app.ui.review_panel.reextract_record_into_draft"
        ) as mock_re:
            panel._on_reextract()
            mock_re.assert_not_called()
        self.assertEqual(emitted, [])

    def test_reextract_draft_only_needs_review_shows_unavailable_warning(self):
        panel, record, session = self._make_panel_with_draft_only_needs_review_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch("app.ui.review_panel.QMessageBox.warning") as mock_warning, patch(
            "app.ui.review_panel.QMessageBox.question"
        ) as mock_question, patch(
            "app.ui.review_panel.QInputDialog.getText"
        ) as mock_get_text, patch("app.ui.review_panel.reextract_record_into_draft") as mock_re:
            panel._on_reextract()
            mock_warning.assert_called_once_with(
                panel,
                "Re-extract Unavailable",
                "Re-extract is unavailable for draft-only Needs Review records. "
                "Delete this record and run extraction again.",
            )
            mock_question.assert_not_called()
            mock_get_text.assert_not_called()
            mock_re.assert_not_called()

        self.assertEqual(panel._field_name.text(), "Sleep")
        self.assertEqual(emitted, [])

    def test_reextract_calls_api_when_user_provides_prompt(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        updated_spell = MagicMock()
        updated_spell.name = "Fireball v2"
        updated_spell.level = 3
        updated_spell.description = "Even bigger"
        updated_spell.review_notes = None

        def _reextract_side_effect(*args, **kwargs):
            record.draft_spell = updated_spell
            record.draft_dirty = True
            return updated_spell

        with patch(
            "app.ui.review_panel.QInputDialog.getText", return_value=("focus on damage", True)
        ), patch(
            "app.ui.review_panel.reextract_record_into_draft", side_effect=_reextract_side_effect
        ) as mock_re:
            panel._on_reextract()
            mock_re.assert_called_once_with(
                session,
                spell_id="abc-123",
                focus_prompt="focus on damage",
                config=panel._config,
            )
            self.assertEqual(panel._field_name.text(), updated_spell.name)
            self.assertIs(record.draft_spell, updated_spell)
            self.assertEqual(emitted, [session])

    def test_reextract_shows_error_and_keeps_ui_consistent_when_api_raises(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        panel._field_name.setText("Stale UI Value")

        with patch(
            "app.ui.review_panel.QInputDialog.getText", return_value=("focus on damage", True)
        ), patch(
            "app.ui.review_panel.reextract_record_into_draft",
            side_effect=RuntimeError("service unavailable"),
        ) as mock_reextract, patch(
            "app.ui.review_panel.QMessageBox.critical"
        ) as mock_critical:
            panel._on_reextract()

            mock_reextract.assert_called_once_with(
                session,
                spell_id="abc-123",
                focus_prompt="focus on damage",
                config=panel._config,
            )
            mock_critical.assert_called_once()
            self.assertNotIn("service unavailable", mock_critical.call_args.args[2])

        self.assertEqual(panel._field_name.text(), "Fireball")
        self.assertIs(panel._stack.currentWidget(), panel._review_widget)

        self.assertFalse(panel._dirty_banner.isVisible())
        self.assertEqual(emitted, [])

    def test_reextract_success_resets_invalid_banner_text(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.apply_review_edits",
            side_effect=ValueError("bad level"),
        ):
            panel._field_level.setText("not-an-int")
            panel._on_field_edited()

        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertEqual(panel._dirty_banner.text(), "Invalid: bad level")

        updated_spell = MagicMock()
        updated_spell.name = "Fireball v2"
        updated_spell.level = 3
        updated_spell.description = "Even bigger"
        updated_spell.review_notes = None

        def _reextract_side_effect(*args, **kwargs):
            record.draft_spell = updated_spell
            record.draft_dirty = True
            return updated_spell

        with patch(
            "app.ui.review_panel.QInputDialog.getText", return_value=("focus on damage", True)
        ), patch(
            "app.ui.review_panel.reextract_record_into_draft", side_effect=_reextract_side_effect
        ):
            panel._on_reextract()

        self.assertTrue(panel._dirty_banner.isVisible())
        self.assertEqual(panel._dirty_banner.text(), "Unsaved changes")
        self.assertEqual(panel._field_name.text(), updated_spell.name)
        self.assertEqual(emitted, [session])

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

    def test_accept_blocked_when_form_is_currently_invalid(self):
        panel, _, session = self._make_panel_with_needs_review_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.apply_review_edits",
            side_effect=ValueError("bad level"),
        ):
            panel._field_level.setText("not-an-int")
            panel._on_field_edited()

        with patch("app.ui.review_panel.QMessageBox.warning") as mock_warning, patch(
            "app.ui.review_panel.accept_review_record"
        ) as mock_accept:
            panel._on_accept()

        mock_warning.assert_called_once()
        self.assertIn("validation errors", mock_warning.call_args.args[2].lower())
        mock_accept.assert_not_called()
        self.assertEqual(emitted, [])

    def test_accept_shows_critical_and_does_not_emit_when_backend_raises(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        with patch(
            "app.ui.review_panel.accept_review_record",
            side_effect=RuntimeError("service unavailable"),
        ) as mock_accept, patch("app.ui.review_panel.QMessageBox.critical") as mock_critical:
            panel._on_accept()
            mock_accept.assert_called_once()
            mock_critical.assert_called_once()
            self.assertNotIn("service unavailable", mock_critical.call_args.args[2])

        self.assertEqual(emitted, [])

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
        panel, _, session = self._make_panel_with_needs_review_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        checked_states = iter([False, False])

        def _is_checked(*_args, **_kwargs) -> bool:
            return next(checked_states, False)

        with patch("app.ui.review_panel.accept_review_record", return_value=False) as mock_accept, patch(
            "app.ui.review_panel.QDialog.exec",
            return_value=QDialog.DialogCode.Accepted,
        ), patch(
            "app.ui.review_panel.QRadioButton.isChecked",
            side_effect=_is_checked,
        ):
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 1)
        self.assertEqual(emitted, [])

    def test_accept_conflict_dialog_accepted_overwrite_calls_overwrite_strategy(self):
        from app.ui.review_panel import DuplicateResolutionStrategy

        panel, _, session = self._make_panel_with_needs_review_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record") as mock_accept, patch(
            "app.ui.review_panel.QDialog.exec",
            autospec=True,
            return_value=QDialog.DialogCode.Accepted,
        ):
            mock_accept.side_effect = [False, True]
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 2)
        self.assertEqual(
            mock_accept.call_args_list[1].kwargs["duplicate_resolution"],
            DuplicateResolutionStrategy.OVERWRITE,
        )
        self.assertEqual(emitted, [session])

    def test_accept_conflict_dialog_accepted_keep_both_calls_keep_both_strategy(self):
        from app.ui.review_panel import DuplicateResolutionStrategy

        panel, _, session = self._make_panel_with_needs_review_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))

        checked_states = iter([False, True])

        def _is_checked(*_args, **_kwargs) -> bool:
            return next(checked_states, False)

        with patch("app.ui.review_panel.accept_review_record") as mock_accept, patch(
            "app.ui.review_panel.QDialog.exec",
            return_value=QDialog.DialogCode.Accepted,
        ), patch(
            "app.ui.review_panel.QRadioButton.isChecked",
            side_effect=_is_checked,
        ):
            mock_accept.side_effect = [False, True]
            panel._on_accept()

        self.assertEqual(mock_accept.call_count, 2)
        self.assertEqual(
            mock_accept.call_args_list[1].kwargs["duplicate_resolution"],
            DuplicateResolutionStrategy.KEEP_BOTH,
        )
        self.assertEqual(emitted, [session])

    def test_accept_conflict_dialog_rejected_leaves_record_uncommitted(self):
        panel, _, _ = self._make_panel_with_needs_review_record()
        with patch("app.ui.review_panel.accept_review_record") as mock_accept, patch(
            "app.ui.review_panel.QDialog.exec",
            autospec=True,
            return_value=QDialog.DialogCode.Rejected,
        ):
            mock_accept.return_value = False
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 1)

    def test_accept_conflict_dialog_accepted_calls_accept_review_record_second_time(self):
        panel, _, session = self._make_panel_with_needs_review_record()
        call_count = [0]

        def mock_accept(*args, **kwargs):
            call_count[0] += 1
            return call_count[0] > 1

        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record", side_effect=mock_accept), patch(
            "app.ui.review_panel.QDialog.exec",
            autospec=True,
            return_value=QDialog.DialogCode.Accepted,
        ):
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

    def test_detect_worker_emits_progress_start_and_completion(self):
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
        progress = []
        worker.progress_updated.connect(lambda current, total: progress.append((current, total)))

        with patch("app.ui.workers.detect_spells", return_value=result_session):
            worker.run()

        self.assertEqual(progress, [(0, 1), (1, 1)])

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
        session_ready = []
        spells_detected = []
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.session_ready.connect(lambda s: session_ready.append(s))
        worker.spells_detected.connect(lambda n: spells_detected.append(n))

        with patch("app.ui.workers.detect_spells", return_value=MagicMock(records=[])) as mock_detect:
            worker.run()

        self.assertEqual(cancelled, [True])
        mock_detect.assert_not_called()
        self.assertEqual(session_ready, [])
        self.assertEqual(spells_detected, [])

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
        result_session.records = [r2_result, r1_result]

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

        self.assertEqual(extracted, ["id-2", "id-1"])

    def test_extract_worker_emits_progress_start_and_completion(self):
        import threading

        from app.ui.workers import ExtractWorker

        pending_one = MagicMock()
        pending_one.spell_id = "id-1"
        pending_one.status = MagicMock(value="pending_extraction")
        pending_two = MagicMock()
        pending_two.spell_id = "id-2"
        pending_two.status = MagicMock(value="pending_extraction")
        session = MagicMock()
        session.records = [pending_one, pending_two]

        done_one = MagicMock()
        done_one.spell_id = "id-1"
        done_one.status = MagicMock(value="needs_review")
        still_pending = MagicMock()
        still_pending.spell_id = "id-2"
        still_pending.status = MagicMock(value="pending_extraction")
        result_session = MagicMock()
        result_session.records = [done_one, still_pending]

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="all",
        )
        progress = []
        worker.progress_updated.connect(lambda current, total: progress.append((current, total)))

        with patch("app.ui.workers.extract_all_pending", return_value=result_session):
            worker.run()

        self.assertEqual(progress, [(0, 2), (1, 2)])

    def test_extract_worker_selected_mode_progress_uses_selected_pending_scope(self):
        import threading

        from app.ui.workers import ExtractWorker

        pending_one = MagicMock()
        pending_one.spell_id = "id-1"
        pending_one.status = MagicMock(value="pending_extraction")
        pending_two = MagicMock()
        pending_two.spell_id = "id-2"
        pending_two.status = MagicMock(value="pending_extraction")
        session = MagicMock()
        session.records = [pending_one, pending_two]
        session.selected_spell_id = "id-2"

        still_pending = MagicMock()
        still_pending.spell_id = "id-1"
        still_pending.status = MagicMock(value="pending_extraction")
        selected_done = MagicMock()
        selected_done.spell_id = "id-2"
        selected_done.status = MagicMock(value="needs_review")
        result_session = MagicMock()
        result_session.records = [still_pending, selected_done]

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="selected",
        )
        progress = []
        worker.progress_updated.connect(lambda current, total: progress.append((current, total)))

        with patch("app.ui.workers.extract_selected_pending", return_value=result_session):
            worker.run()

        self.assertEqual(progress, [(0, 1), (1, 1)])

    def test_extract_worker_selected_mode_progress_zero_when_selected_not_pending(self):
        import threading

        from app.ui.workers import ExtractWorker

        pending_one = MagicMock()
        pending_one.spell_id = "id-1"
        pending_one.status = MagicMock(value="pending_extraction")
        selected_non_pending = MagicMock()
        selected_non_pending.spell_id = "id-2"
        selected_non_pending.status = MagicMock(value="needs_review")
        session = MagicMock()
        session.records = [pending_one, selected_non_pending]
        session.selected_spell_id = "id-2"

        result_session = MagicMock()
        result_session.records = [pending_one, selected_non_pending]

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="selected",
        )
        progress = []
        worker.progress_updated.connect(lambda current, total: progress.append((current, total)))

        with patch("app.ui.workers.extract_selected_pending", return_value=result_session):
            worker.run()

        self.assertEqual(progress, [(0, 0), (0, 0)])

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

    def test_extract_worker_emits_final_progress_before_extraction_complete(self):
        import threading

        from app.ui.workers import ExtractWorker

        pending = MagicMock()
        pending.spell_id = "id-1"
        pending.status = MagicMock(value="pending_extraction")
        extracted = MagicMock()
        extracted.spell_id = "id-1"
        extracted.status = MagicMock(value="needs_review")

        session = MagicMock()
        session.records = [pending]

        result_session = MagicMock()
        result_session.records = [extracted]

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="all",
        )

        progress = []
        signal_order = []
        worker.progress_updated.connect(
            lambda current, total: (progress.append((current, total)), signal_order.append("progress"))
        )
        worker.extraction_complete.connect(lambda _: signal_order.append("extraction_complete"))

        with patch("app.ui.workers.extract_all_pending", return_value=result_session):
            worker.run()

        self.assertEqual(progress, [(0, 1), (1, 1)])
        self.assertEqual(signal_order[-2:], ["progress", "extraction_complete"])

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
            args, kwargs = mock_sel.call_args
            self.assertIsNot(args[0], session)
            self.assertIs(kwargs["config"], worker._config)

    def test_extract_worker_passes_cloned_session_state_to_extract_all(self):
        import threading

        from app.ui.workers import ExtractWorker

        r1 = MagicMock()
        r1.spell_id = "id-1"
        r1.status = MagicMock(value="pending_extraction")
        session = MagicMock()
        session.records = [r1]
        config = MagicMock()
        result_session = MagicMock()
        result_session.records = [r1]

        worker = ExtractWorker(
            session_state=session,
            config=config,
            cancel_event=threading.Event(),
            mode="all",
        )

        with patch("app.ui.workers.extract_all_pending", return_value=result_session) as mock_extract:
            worker.run()

        mock_extract.assert_called_once()
        args, kwargs = mock_extract.call_args
        self.assertIsNot(args[0], session)
        self.assertIs(kwargs["config"], config)

    def test_extract_worker_emits_failed_on_exception(self):
        import threading

        from app.ui.workers import ExtractWorker

        worker = ExtractWorker(
            session_state=MagicMock(records=[]),
            config=MagicMock(),
            cancel_event=threading.Event(),
            mode="all",
        )
        contract_failures = []
        legacy_failures = []
        worker.extraction_failed.connect(lambda title, msg: contract_failures.append((title, msg)))
        worker.failed.connect(lambda title, msg: legacy_failures.append((title, msg)))

        with patch("app.ui.workers.extract_all_pending", side_effect=RuntimeError("boom")):
            worker.run()

        self.assertEqual(len(contract_failures), 1)
        self.assertEqual(len(legacy_failures), 1)
        self.assertIn("Extraction Failed", contract_failures[0][0])
        self.assertIn("boom", contract_failures[0][1])
        self.assertEqual(contract_failures, legacy_failures)

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
            contract_cancelled_calls = []
            legacy_cancelled_calls = []
            worker.extraction_cancelled.connect(lambda: contract_cancelled_calls.append(True))
            worker.cancelled.connect(lambda: legacy_cancelled_calls.append(True))
            worker.run()
        mock_extract.assert_not_called()
        self.assertEqual(contract_cancelled_calls, [True])
        self.assertEqual(legacy_cancelled_calls, [True])

    def test_cancel_mid_record_drops_only_inflight_record_deferred(self):
        self.skipTest(
            "Per-record mid-batch cancellation requires streaming callbacks in extraction API."
        )

    def test_extract_worker_cancelled_after_extraction_emits_complete_then_cancelled(self):
        import threading

        from app.ui.workers import ExtractWorker

        session = MagicMock()
        config = MagicMock()
        cancel_event = threading.Event()
        result_session = MagicMock()
        complete_calls = []
        cancelled_calls = []
        signal_order = []

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
            worker.extraction_complete.connect(
                lambda s: (complete_calls.append(s), signal_order.append("extraction_complete"))
            )
            worker.cancelled.connect(
                lambda: (cancelled_calls.append(True), signal_order.append("cancelled"))
            )
            worker.run()
        self.assertEqual(complete_calls, [result_session])
        self.assertEqual(cancelled_calls, [True])
        self.assertEqual(signal_order, ["extraction_complete", "cancelled"])

    def test_detect_worker_passes_cloned_session_state_to_detect_spells(self):
        import threading

        from app.ui.workers import DetectSpellsWorker

        session = MagicMock()
        routed = MagicMock()
        config = MagicMock()
        with patch("app.ui.workers.detect_spells") as mock_detect:
            mock_detect.return_value = MagicMock(records=[])
            worker = DetectSpellsWorker(
                routed_document=routed,
                config=config,
                session_state=session,
                cancel_event=threading.Event(),
            )
            worker.run()
        mock_detect.assert_called_once()
        args, kwargs = mock_detect.call_args
        self.assertIs(args[0], routed)
        self.assertIs(kwargs["config"], config)
        self.assertIsNot(kwargs["session_state"], session)

    def test_detect_worker_cancelled_after_detection_emits_session_ready_then_cancelled(self):
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
        spells_detected_calls = []
        cancelled_calls = []
        signal_order = []

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
            worker.session_ready.connect(
                lambda s: (ready_calls.append(s), signal_order.append("session_ready"))
            )
            worker.spells_detected.connect(
                lambda n: (spells_detected_calls.append(n), signal_order.append("spells_detected"))
            )
            worker.cancelled.connect(
                lambda: (cancelled_calls.append(True), signal_order.append("cancelled"))
            )
            worker.run()
        self.assertEqual(ready_calls, [result_session])
        self.assertEqual(spells_detected_calls, [2])
        self.assertEqual(cancelled_calls, [True])
        self.assertEqual(signal_order, ["session_ready", "spells_detected", "cancelled"])


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
        session.selected_spell_id = None
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

    def test_close_event_sets_cancel_and_stops_running_thread(self):
        import threading

        win = self._make_window_with_session()
        cancel_event = threading.Event()
        thread = MagicMock()
        thread.isRunning.return_value = True
        thread.wait.return_value = True

        win._worker_running = True
        win._cancel_event = cancel_event
        win._active_thread = thread

        event = MagicMock()
        with patch("app.ui.main_window.QMainWindow.closeEvent") as mock_super_close:
            win.closeEvent(event)

        self.assertTrue(cancel_event.is_set())
        thread.quit.assert_called_once_with()
        thread.wait.assert_called_once_with(2000)
        event.ignore.assert_not_called()
        mock_super_close.assert_called_once_with(event)

    def test_close_event_ignores_close_when_thread_wait_times_out(self):
        import threading

        win = self._make_window_with_session()
        cancel_event = threading.Event()
        thread = MagicMock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False

        win._worker_running = True
        win._cancel_event = cancel_event
        win._active_thread = thread

        event = MagicMock()
        with patch("app.ui.main_window.QMainWindow.closeEvent") as mock_super_close:
            win.closeEvent(event)

        self.assertTrue(cancel_event.is_set())
        thread.quit.assert_called_once_with()
        thread.wait.assert_called_once_with(2000)
        event.ignore.assert_called_once_with()
        thread.terminate.assert_not_called()
        thread.exit.assert_not_called()
        mock_super_close.assert_not_called()

    def test_close_event_skips_thread_shutdown_when_thread_not_running(self):
        import threading

        win = self._make_window_with_session()
        cancel_event = threading.Event()
        thread = MagicMock()
        thread.isRunning.return_value = False

        win._worker_running = True
        win._cancel_event = cancel_event
        win._active_thread = thread

        event = MagicMock()
        with patch("app.ui.main_window.QMainWindow.closeEvent") as mock_super_close:
            win.closeEvent(event)

        self.assertTrue(cancel_event.is_set())
        thread.quit.assert_not_called()
        thread.wait.assert_not_called()
        mock_super_close.assert_called_once_with(event)

    def test_close_event_waits_for_running_thread_when_worker_flag_is_false(self):
        import threading

        win = self._make_window_with_session()
        cancel_event = threading.Event()
        thread = MagicMock()
        thread.isRunning.return_value = True
        thread.wait.return_value = True

        win._worker_running = False
        win._cancel_event = cancel_event
        win._active_thread = thread

        event = MagicMock()
        with patch("app.ui.main_window.QMainWindow.closeEvent") as mock_super_close:
            win.closeEvent(event)

        self.assertTrue(cancel_event.is_set())
        thread.quit.assert_called_once_with()
        thread.wait.assert_called_once_with(2000)
        event.ignore.assert_not_called()
        mock_super_close.assert_called_once_with(event)

    def test_status_bar_updates_on_spells_detected(self):
        win = self._make_window_with_session()
        mock_panel = MagicMock()
        win._spell_list_panel = mock_panel
        win._on_spells_detected(7)
        self.assertIn("7", win._status_bar.currentMessage())
        mock_panel.refresh.assert_called_once_with(win._session, selected_spell_id=None)

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

    def test_detect_worker_connects_progress_signal(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.DetectSpellsWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker

            win._on_detect_spells()

            mock_worker.progress_updated.connect.assert_any_call(win._on_worker_progress)

    def test_extract_worker_connects_progress_signal(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker

            win._on_extract_all()

            mock_worker.progress_updated.connect.assert_any_call(win._on_worker_progress)

    def test_extract_worker_wires_contract_failure_and_cancel_signals(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            mock_worker = MagicMock()
            mock_worker.record_extracted = MagicMock()
            mock_worker.extraction_complete = MagicMock()
            mock_worker.extraction_failed = MagicMock()
            mock_worker.extraction_cancelled = MagicMock()
            mock_worker.failed = MagicMock()
            mock_worker.cancelled = MagicMock()
            mock_worker_cls.return_value = mock_worker

            win._on_extract_all()

            mock_worker.extraction_failed.connect.assert_any_call(win._on_worker_failed)
            mock_worker.extraction_cancelled.connect.assert_any_call(win._on_worker_cancelled)
            mock_worker.extraction_failed.connect.assert_any_call(mock_thread.quit)
            mock_worker.extraction_cancelled.connect.assert_any_call(mock_thread.quit)
            mock_worker.failed.connect.assert_not_called()
            mock_worker.cancelled.connect.assert_not_called()

    def test_extract_worker_wires_contract_signals_when_legacy_missing(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            mock_worker = SimpleNamespace(
                record_extracted=MagicMock(),
                extraction_complete=MagicMock(),
                extraction_failed=MagicMock(),
                extraction_cancelled=MagicMock(),
                progress_updated=MagicMock(),
                moveToThread=MagicMock(),
                run=MagicMock(),
                deleteLater=MagicMock(),
            )
            mock_worker_cls.return_value = mock_worker

            win._on_extract_all()

            mock_worker.extraction_failed.connect.assert_any_call(win._on_worker_failed)
            mock_worker.extraction_cancelled.connect.assert_any_call(win._on_worker_cancelled)
            mock_worker.extraction_failed.connect.assert_any_call(mock_thread.quit)
            mock_worker.extraction_cancelled.connect.assert_any_call(mock_thread.quit)

    def test_extract_worker_wires_legacy_signals_when_contract_missing(self):
        win = self._make_window_with_session()
        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            mock_worker = SimpleNamespace(
                record_extracted=MagicMock(),
                extraction_complete=MagicMock(),
                failed=MagicMock(),
                cancelled=MagicMock(),
                progress_updated=MagicMock(),
                moveToThread=MagicMock(),
                run=MagicMock(),
                deleteLater=MagicMock(),
            )
            mock_worker_cls.return_value = mock_worker

            win._on_extract_all()

            mock_worker.failed.connect.assert_any_call(win._on_worker_failed)
            mock_worker.cancelled.connect.assert_any_call(win._on_worker_cancelled)
            mock_worker.failed.connect.assert_any_call(mock_thread.quit)
            mock_worker.cancelled.connect.assert_any_call(mock_thread.quit)

    def test_extraction_complete_refreshes_spell_list(self):
        win = self._make_window_with_session()
        mock_panel = MagicMock()
        win._spell_list_panel = mock_panel
        updated_session = MagicMock()
        updated_session.records = []
        updated_session.last_open_path = "/tmp/test.pdf"
        updated_session.selected_spell_id = None
        win._on_extraction_complete(updated_session)
        mock_panel.refresh.assert_called_once_with(updated_session, selected_spell_id=None)

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

    def test_no_op_selected_run_reports_zero_extracted(self):
        win = self._make_window_with_session()
        win._spell_list_panel = MagicMock()

        confirmed = MagicMock()
        confirmed.spell_id = "id-confirmed"
        confirmed.status = MagicMock(value="confirmed")

        pending = MagicMock()
        pending.spell_id = "id-pending"
        pending.status = MagicMock(value="pending_extraction")

        win._session.records = [confirmed, pending]
        win._session.selected_spell_id = "id-confirmed"

        with patch("app.ui.main_window.QThread") as mock_thread_cls, patch(
            "app.ui.main_window.ExtractWorker"
        ) as mock_worker_cls:
            mock_thread_cls.return_value = MagicMock()
            mock_worker_cls.return_value = MagicMock()
            win._start_extract_worker(mode="selected")

        updated_session = MagicMock()
        updated_session.records = [confirmed, pending]
        updated_session.last_open_path = "/tmp/test.pdf"
        updated_session.selected_spell_id = "id-confirmed"

        win._on_extraction_complete(updated_session)

        self.assertIn("0 spell(s) extracted", win._status_bar.currentMessage())

    def test_extract_worker_signal_order_keeps_completion_status_final_after_cancel(self):
        import threading

        from app.ui.workers import ExtractWorker

        win = self._make_window_with_session()
        win._spell_list_panel = MagicMock()

        pending = MagicMock()
        pending.spell_id = "id-1"
        pending.status = MagicMock(value="pending_extraction")

        extracted = MagicMock()
        extracted.spell_id = "id-1"
        extracted.status = MagicMock(value="needs_review")

        session = MagicMock()
        session.records = [pending]
        session.selected_spell_id = None
        session.last_open_path = "/tmp/test.pdf"

        updated_session = MagicMock()
        updated_session.records = [extracted]
        updated_session.selected_spell_id = None
        updated_session.last_open_path = "/tmp/test.pdf"

        cancel_event = threading.Event()

        worker = ExtractWorker(
            session_state=session,
            config=MagicMock(),
            cancel_event=cancel_event,
            mode="all",
        )

        # Mirror active extraction state so cancellation handler takes real branch.
        win._worker_running = True
        win._extract_scope_spell_ids = {"id-1"}
        cancel_handler = MagicMock(wraps=win._on_worker_cancelled)

        worker.progress_updated.connect(win._on_worker_progress)
        worker.extraction_complete.connect(win._on_extraction_complete)
        worker.extraction_cancelled.connect(cancel_handler)

        def _extract_and_cancel(session_state, *, config):
            del session_state, config
            cancel_event.set()
            return updated_session

        with patch("app.ui.workers.extract_all_pending", side_effect=_extract_and_cancel):
            worker.run()

        cancel_handler.assert_called_once_with()
        self.assertTrue(cancel_event.is_set())
        self.assertIn("Extraction complete - 1 spell(s) extracted.", win._status_bar.currentMessage())
        self.assertNotIn("Operation cancelled.", win._status_bar.currentMessage())

    def test_worker_progress_status_bar_message_with_known_total(self):
        win = self._make_window_with_session()

        win._on_worker_progress(2, 5)

        self.assertIn("2/5", win._status_bar.currentMessage())
        self.assertIn("40%", win._status_bar.currentMessage())

    def test_worker_progress_status_bar_message_with_zero_total(self):
        win = self._make_window_with_session()

        win._on_worker_progress(3, 0)

        self.assertIn("3 item(s) complete", win._status_bar.currentMessage())
        self.assertIn("unknown", win._status_bar.currentMessage().lower())


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
        win._routed_document = RoutedDocument(
            source_path=Path("/old/path.pdf"),
            source_sha256_hex="a" * 64,
            file_type="pdf",
            ingestion_mode="pdf_digital",
            markdown_text="",
            coordinate_map=CoordinateAwareTextMap(lines=[]),
            default_source_pages=[],
            identity=DocumentIdentityMetadata(
                source_sha256_hex="a" * 64,
                source_display_name="Player's Handbook",
                page_offset=0,
                force_ocr=False,
            ),
        )

        same_path = "/new/same-file.pdf"
        with patch("app.ui.main_window.compute_sha256_hex", return_value="a" * 64), patch(
            "app.ui.main_window.route_document"
        ) as mock_route:
            win._open_document(same_path)

        mock_route.assert_not_called()
        self.assertIn("same-file.pdf", win.windowTitle())
        self.assertIn(Path(same_path).name, win._status_bar.currentMessage())
        self.assertIs(win._session, existing_session)
        self.assertEqual(win._session.last_open_path, same_path)
        self.assertEqual(win._routed_document.source_path, Path(same_path))
        self.assertEqual(win._config.last_import_directory, str(Path(same_path).parent))
        win._config.save.assert_called_once()

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
        win._config.save.assert_not_called()

    def test_restored_session_with_unknown_sha_prompts_identity_before_routing(self):
        win = self._make_window()
        restored_session = MagicMock()
        restored_session.records = []
        restored_session.selected_spell_id = None
        new_sha = "b" * 64
        dialog_executed = False
        observed_events = []

        class _ObservedMap(dict):
            def __setitem__(self, key, value):
                observed_events.append(("identity_name_set", key, value))
                super().__setitem__(key, value)

        win._config.document_names_by_sha256 = _ObservedMap()

        routed = MagicMock()
        routed.coordinate_map = CoordinateAwareTextMap(lines=[])

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=restored_session
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg

            def _exec_dialog():
                nonlocal dialog_executed
                dialog_executed = True
                return QDialog.DialogCode.Accepted

            mock_dlg.exec.side_effect = _exec_dialog
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Player's Handbook",
                page_offset=2,
                force_ocr=True,
            )

            def _route_document(*_args, **kwargs):
                observed_events.append(("route_called",))
                self.assertTrue(dialog_executed)
                self.assertIs(kwargs.get("config"), win._config)
                self.assertEqual(
                    win._config.document_names_by_sha256[new_sha],
                    "Player's Handbook",
                )
                self.assertEqual(win._config.document_offsets[new_sha], 2)
                self.assertTrue(win._config.force_ocr_by_sha256[new_sha])
                return routed

            mock_route.side_effect = _route_document

            win._open_document("/some/new-file.pdf")

        mock_dlg_cls.assert_called_once()
        mock_route.assert_called_once()

        name_set_index = observed_events.index(
            ("identity_name_set", new_sha, "Player's Handbook")
        )
        route_called_index = observed_events.index(("route_called",))
        self.assertLess(name_set_index, route_called_index)

        self.assertEqual(
            win._config.document_names_by_sha256[new_sha],
            "Player's Handbook",
        )
        self.assertEqual(win._config.document_offsets[new_sha], 2)
        self.assertTrue(win._config.force_ocr_by_sha256[new_sha])
        self.assertIs(win._session, restored_session)
        win._config.save.assert_called_once()

    def test_identity_staging_rolls_back_when_routing_fails(self):
        win = self._make_window()
        original_session = MagicMock()
        original_session.source_sha256_hex = "a" * 64
        win._session = original_session

        new_sha = "d" * 64
        win._config.document_offsets[new_sha] = 9
        win._config.force_ocr_by_sha256[new_sha] = False

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document",
            side_effect=RuntimeError("route failed"),
        ) as mock_route, patch("app.ui.main_window.QMessageBox.critical") as mock_critical:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Dungeon Master's Guide",
                page_offset=2,
                force_ocr=True,
            )

            win._open_document("/some/new-file.pdf")

        mock_route.assert_called_once()
        mock_critical.assert_called_once()
        self.assertNotIn(new_sha, win._config.document_names_by_sha256)
        self.assertEqual(win._config.document_offsets[new_sha], 9)
        self.assertFalse(win._config.force_ocr_by_sha256[new_sha])
        self.assertIs(win._session, original_session)
        win._config.save.assert_not_called()

    def test_blank_identity_name_falls_back_to_default_source_document_when_stored(self):
        win = self._make_window()
        restored_session = MagicMock()
        restored_session.records = []
        restored_session.selected_spell_id = None
        new_sha = "c" * 64

        routed = MagicMock()
        routed.coordinate_map = CoordinateAwareTextMap(lines=[])

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=restored_session
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document", return_value=routed
        ):
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="",
                page_offset=0,
                force_ocr=False,
            )

            win._open_document("/some/blank-name.pdf")

        self.assertEqual(
            win._config.document_names_by_sha256[new_sha],
            win._config.default_source_document,
        )
        self.assertIs(win._session, restored_session)
        win._config.save.assert_called_once()

    def test_identity_page_offset_zero_clears_stale_offset_after_successful_open(self):
        win = self._make_window()
        restored_session = MagicMock()
        restored_session.records = []
        restored_session.selected_spell_id = None
        new_sha = "e" * 64
        win._config.document_offsets[new_sha] = 7
        saw_offset_at_route = None

        routed = MagicMock()
        routed.coordinate_map = CoordinateAwareTextMap(lines=[])

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=restored_session
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Monster Manual",
                page_offset=0,
                force_ocr=False,
            )

            def _route_document(*_args, **_kwargs):
                nonlocal saw_offset_at_route
                saw_offset_at_route = new_sha in win._config.document_offsets
                return routed

            mock_route.side_effect = _route_document

            win._open_document("/some/offset-zero.pdf")

        self.assertFalse(saw_offset_at_route)
        self.assertNotIn(new_sha, win._config.document_offsets)
        self.assertIs(win._session, restored_session)
        win._config.save.assert_called_once()

    def test_identity_offset_clear_rolls_back_when_routing_fails(self):
        win = self._make_window()
        original_session = MagicMock()
        original_session.source_sha256_hex = "a" * 64
        win._session = original_session

        new_sha = "f" * 64
        win._config.document_offsets[new_sha] = 9
        saw_offset_at_route = None

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route, patch("app.ui.main_window.QMessageBox.critical") as mock_critical:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Dungeon Master's Guide",
                page_offset=0,
                force_ocr=False,
            )

            def _route_document(*_args, **_kwargs):
                nonlocal saw_offset_at_route
                saw_offset_at_route = new_sha in win._config.document_offsets
                raise RuntimeError("route failed")

            mock_route.side_effect = _route_document

            win._open_document("/some/offset-zero-fail.pdf")

        mock_route.assert_called_once()
        mock_critical.assert_called_once()
        self.assertFalse(saw_offset_at_route)
        self.assertNotIn(new_sha, win._config.document_names_by_sha256)
        self.assertEqual(win._config.document_offsets[new_sha], 9)
        self.assertIs(win._session, original_session)
        win._config.save.assert_not_called()

    def test_identity_force_ocr_false_clears_stale_force_ocr_after_successful_open(self):
        win = self._make_window()
        restored_session = MagicMock()
        restored_session.records = []
        restored_session.selected_spell_id = None
        new_sha = "1" * 64
        win._config.force_ocr_by_sha256[new_sha] = True
        saw_force_ocr_at_route = None

        routed = MagicMock()
        routed.coordinate_map = CoordinateAwareTextMap(lines=[])

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=restored_session
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Monster Manual",
                page_offset=0,
                force_ocr=False,
            )

            def _route_document(*_args, **_kwargs):
                nonlocal saw_force_ocr_at_route
                saw_force_ocr_at_route = new_sha in win._config.force_ocr_by_sha256
                return routed

            mock_route.side_effect = _route_document

            win._open_document("/some/force-ocr-false.pdf")

        self.assertFalse(saw_force_ocr_at_route)
        self.assertNotIn(new_sha, win._config.force_ocr_by_sha256)
        self.assertIs(win._session, restored_session)
        win._config.save.assert_called_once()

    def test_identity_force_ocr_clear_rolls_back_when_routing_fails(self):
        win = self._make_window()
        original_session = MagicMock()
        original_session.source_sha256_hex = "a" * 64
        win._session = original_session

        new_sha = "2" * 64
        win._config.force_ocr_by_sha256[new_sha] = True
        saw_force_ocr_at_route = None

        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), patch(
            "app.ui.main_window.restore_session_state_for_source", return_value=None
        ), patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, patch(
            "app.ui.main_window.route_document"
        ) as mock_route, patch("app.ui.main_window.QMessageBox.critical") as mock_critical:
            mock_dlg = MagicMock()
            mock_dlg_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
            mock_dlg.get_result.return_value = SimpleNamespace(
                source_display_name="Dungeon Master's Guide",
                page_offset=0,
                force_ocr=False,
            )

            def _route_document(*_args, **_kwargs):
                nonlocal saw_force_ocr_at_route
                saw_force_ocr_at_route = new_sha in win._config.force_ocr_by_sha256
                raise RuntimeError("route failed")

            mock_route.side_effect = _route_document

            win._open_document("/some/force-ocr-false-fail.pdf")

        mock_route.assert_called_once()
        mock_critical.assert_called_once()
        self.assertFalse(saw_force_ocr_at_route)
        self.assertTrue(win._config.force_ocr_by_sha256[new_sha])
        self.assertIs(win._session, original_session)
        win._config.save.assert_not_called()

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

    def test_accepted_dialog_allows_negative_page_offset(self):
        from app.ui.identity_dialog import DocumentIdentityDialog

        dlg = DocumentIdentityDialog(
            sha256_hex="a" * 64,
            default_document_name="PHB",
        )
        dlg._offset_spin.setValue(-3)

        result = dlg.get_result()

        self.assertEqual(result.page_offset, -3)


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

    def _make_confirmed_record(self, spell_id: str, *, name: str = "Fireball"):
        record = MagicMock()
        record.spell_id = spell_id
        record.status = MagicMock(value="confirmed")
        record.boundary_start_line = 0
        record.boundary_end_line = -1
        record.section_order = 0
        spell = MagicMock()
        spell.name = name
        spell.level = 3
        spell.description = "Test description"
        spell.class_list = "Wizard"
        spell.school = []
        spell.sphere = []
        spell.components = []
        spell.range = ""
        spell.casting_time = ""
        spell.duration = ""
        spell.area_of_effect = ""
        spell.saving_throw = ""
        spell.reversible = False
        spell.needs_review = False
        spell.review_notes = None
        record.draft_spell = spell
        record.canonical_spell = spell
        return record

    def _make_session_for_records(self, records, *, selected_spell_id=None):
        session = MagicMock()
        session.records = list(records)
        session.selected_spell_id = selected_spell_id
        session.coordinate_map = MagicMock()
        session.coordinate_map.regions_for_range.return_value = []
        return session

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
        new_session.records = []
        new_session.selected_spell_id = None
        win._spell_list_panel = MagicMock()
        win._set_session(new_session, source_path="test.pdf")
        win._spell_list_panel.refresh.assert_called_once_with(
            new_session,
            selected_spell_id=None,
        )

    def test_set_session_restores_selected_spell_id_into_spell_list(self):
        win = self._make_window_with_panels()
        selected_spell_id = "spell-restore"
        record = self._make_confirmed_record(selected_spell_id)
        session = self._make_session_for_records(
            [record],
            selected_spell_id=selected_spell_id,
        )

        with patch.object(win._review_panel, "show_review_record") as mock_review:
            win._set_session(session, source_path="test.pdf")

        selected_items = win._spell_list_panel._confirmed_list.selectedItems()
        self.assertEqual(len(selected_items), 1)
        self.assertEqual(
            selected_items[0].data(Qt.ItemDataRole.UserRole),
            selected_spell_id,
        )
        mock_review.assert_called_once_with(record, session)

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

    def test_clearing_spell_selection_resets_upstream_state(self):
        win = self._make_window_with_panels()
        session = MagicMock()
        session.records = []
        session.selected_spell_id = "spell-42"
        win._session = session

        with patch.object(win._review_panel, "show_placeholder") as mock_review_placeholder, patch.object(
            win._doc_panel, "show_placeholder"
        ) as mock_doc_placeholder:
            win._on_spell_selected("")

        self.assertIsNone(session.selected_spell_id)
        mock_review_placeholder.assert_called_once()
        mock_doc_placeholder.assert_called_once()

    def test_review_session_refresh_preserves_selection_without_placeholder_reset(self):
        win = self._make_window_with_panels()
        selected_spell_id = "spell-keep"

        record = self._make_confirmed_record(selected_spell_id)
        session = self._make_session_for_records([record], selected_spell_id=selected_spell_id)
        win._session = session
        win._spell_list_panel.refresh(session)
        win._spell_list_panel._confirmed_list.setCurrentRow(0)

        self.assertEqual(session.selected_spell_id, selected_spell_id)

        updated_record = self._make_confirmed_record(selected_spell_id, name="Fireball Updated")
        updated_session = self._make_session_for_records(
            [updated_record],
            selected_spell_id=selected_spell_id,
        )

        with patch.object(win._review_panel, "show_placeholder") as mock_review_placeholder, patch.object(
            win._doc_panel, "show_placeholder"
        ) as mock_doc_placeholder:
            win._on_review_session_changed(updated_session)

        selected_items = win._spell_list_panel._confirmed_list.selectedItems()
        self.assertEqual(len(selected_items), 1)
        self.assertEqual(
            selected_items[0].data(Qt.ItemDataRole.UserRole),
            selected_spell_id,
        )
        mock_review_placeholder.assert_not_called()
        mock_doc_placeholder.assert_called_once()

    def test_review_session_refresh_restores_selection_from_updated_session_state(self):
        win = self._make_window_with_panels()
        selected_spell_id = "spell-restored-on-refresh"
        updated_record = self._make_confirmed_record(selected_spell_id)
        updated_session = self._make_session_for_records(
            [updated_record],
            selected_spell_id=selected_spell_id,
        )

        with patch.object(win._review_panel, "show_review_record") as mock_review:
            win._on_review_session_changed(updated_session)

        selected_items = win._spell_list_panel._confirmed_list.selectedItems()
        self.assertEqual(len(selected_items), 1)
        self.assertEqual(
            selected_items[0].data(Qt.ItemDataRole.UserRole),
            selected_spell_id,
        )
        mock_review.assert_called_once_with(updated_record, updated_session)

    def test_review_session_refresh_removal_emits_deselection_through_panel_signal(self):
        win = self._make_window_with_panels()
        selected_spell_id = "spell-drop"

        record = self._make_confirmed_record(selected_spell_id)
        session = self._make_session_for_records([record])
        win._session = session
        win._spell_list_panel.refresh(session)
        win._spell_list_panel._confirmed_list.setCurrentRow(0)

        self.assertEqual(session.selected_spell_id, selected_spell_id)

        updated_session = self._make_session_for_records([])

        with patch.object(win._review_panel, "show_placeholder") as mock_review_placeholder, patch.object(
            win._doc_panel, "show_placeholder"
        ) as mock_doc_placeholder:
            win._on_review_session_changed(updated_session)

        self.assertIs(win._session, updated_session)
        self.assertIsNone(updated_session.selected_spell_id)
        self.assertEqual(len(win._spell_list_panel._confirmed_list.selectedItems()), 0)
        mock_review_placeholder.assert_called_once()
        mock_doc_placeholder.assert_called_once()

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
