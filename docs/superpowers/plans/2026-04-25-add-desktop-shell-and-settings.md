# Desktop Shell and Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PySide6 three-panel desktop workbench (document viewer, spell list, review editor) plus settings dialog, wired to all existing extraction and session APIs.

**Architecture:** `SpellScribeMainWindow` hosts three panels in a `QSplitter`, reads `SessionState` as its single source of truth, and dispatches background jobs via `QThread`/`QObject` workers. The settings dialog makes an in-memory copy of `AppConfig` and writes only on Save, ensuring no mid-job config mutations.

**Tech Stack:** PySide6 6.7+, PyMuPDF (fitz) for PDF rendering, existing `app.pipeline.extraction` API surface, `app.config.AppConfig`, `app.session.SessionState`

---

## File Map

| Status | File | Responsibility |
|--------|------|---------------|
| Create | `app/ui/__init__.py` | UI package init |
| Create | `app/ui/main_window.py` | `SpellScribeMainWindow` — window shell, toolbar, splitter, document open flow, worker orchestration |
| Create | `app/ui/document_panel.py` | `DocumentPanel` — PDF rendering via fitz + QPainter overlays, DOCX in read-only QTextEdit |
| Create | `app/ui/spell_list_panel.py` | `SpellListPanel` — three-section list (Confirmed / Needs Review / Pending), selection signal |
| Create | `app/ui/review_panel.py` | `ReviewPanel` — stacked widget: pending status view OR review editor with dirty indicator and action buttons |
| Create | `app/ui/workers.py` | `DetectSpellsWorker`, `ExtractWorker` — QObject workers with typed signals, cancel via `threading.Event` |
| Create | `app/ui/settings_dialog.py` | `SettingsDialog` — `AppConfig` editor with credential-source radio group and Test API Key button |
| Modify | `requirements.txt` | Add `PySide6>=6.7,<7` |
| Create | `tests/test_ui_main_window.py` | Main window, toolbar state, document open flow, same-SHA/different-SHA logic |
| Create | `tests/test_ui_settings_dialog.py` | Settings persistence, cancel no-op, credential mode toggling, confirmation checkbox |

---

## Prerequisites: What Already Exists

All pipeline APIs are implemented and importable. Use them as-is; do not reimplement.

```python
# Session persistence
from app.session import (
    SessionState, SpellRecord, SpellRecordStatus,
    save_session_state, load_session_state,
    restore_session_state_for_source,
)

# Extraction service functions
from app.pipeline.extraction import (
    detect_spells,           # (routed_doc, *, config, ...) -> SessionState
    extract_all_pending,     # (session_state, *, config, stage2_caller=None) -> SessionState
    extract_selected_pending, # (session_state, *, config, stage2_caller=None) -> SessionState
    get_review_draft,        # (record) -> Spell
    apply_review_edits,      # (record, *, draft_updates, config) -> Spell
    save_confirmed_changes,  # (session_state, *, spell_id, config=None) -> SpellRecord
    accept_review_record,    # (session_state, *, spell_id, duplicate_resolution=..., config=None) -> bool
    discard_record_draft,    # (record) -> None
    reextract_record_into_draft, # (session_state, *, spell_id, focus_prompt, config, stage2_caller=None) -> Spell
    delete_record,           # (session_state, *, spell_id) -> bool
    get_confirmed_save_duplicate_conflict, # (session_state, *, spell_id) -> SpellRecord | None
    DuplicateResolutionStrategy,  # Enum: OVERWRITE, KEEP_BOTH, SKIP
    RecordNotFoundError, InvalidRecordStateError, DuplicateConfirmedSpellError,
)

# Document routing (ingestion entry point)
from app.pipeline.ingestion import route_document, RoutedDocument

# Identity
from app.pipeline.identity import (
    compute_sha256_hex,
    DocumentIdentityInput,
    UnknownDocumentIdentityError,
)

# Config
from app.config import AppConfig, CREDENTIAL_ACCOUNT_NAME, CREDENTIAL_SERVICE_NAME

# Models
from app.models import CoordinateAwareTextMap, TextRegion, Spell
```

---

## Task 0: Add PySide6 and Create the ui Package

**Files:**
- Modify: `requirements.txt`
- Create: `app/ui/__init__.py`

- [x] **Step 0.1: Add PySide6 to requirements.txt**

  Append after `python-docx>=1.2,<2`:
  ```
  PySide6>=6.7,<7
  ```

- [x] **Step 0.2: Install the new dependency**

  ```pwsh
  pip install "PySide6>=6.7,<7"
  ```
  Expected: PySide6 and its Qt dependencies install without error.

- [x] **Step 0.3: Create the ui package**

  Create `app/ui/__init__.py` with empty content (just a docstring is fine):
  ```python
  """SpellScribe desktop UI package."""
  ```

- [x] **Step 0.4: Verify PySide6 import works**

  ```pwsh
  python -c "from PySide6.QtWidgets import QApplication; print('PySide6 OK')"
  ```
  Expected output: `PySide6 OK`

- [x] **Step 0.5: Commit**

  ```pwsh
  git add requirements.txt app/ui/__init__.py
  git commit -m "feat: add PySide6 dependency and create app/ui package"
  ```

---

## Task 1: Main Window Shell and Toolbar

**Files:**
- Create: `app/ui/main_window.py`
- Create: `tests/test_ui_main_window.py`

The main window hosts the three-panel layout and owns the toolbar action enable/disable rules.

> **Note:** Export action is permanently disabled in this change. The triggered signal is wired to `_on_export` stub for future integration.

> **Out-of-scope in this change:** The spec scenario "Export action opens the export flow" is intentionally deferred. Per `design.md`, the Export toolbar action is disabled with a tooltip when the export UI dialog is not yet integrated. The export *pipeline* (`app/pipeline/export.py`) exists but the export *dialog* will be built in a future change. The `_on_export` stub is wired to the action for that future integration.

### Step 1.1: Write failing tests for the main window shell

Create `tests/test_ui_main_window.py`:

```python
"""Tests for SpellScribeMainWindow shell and toolbar."""
from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolBar
from app.models import CoordinateAwareTextMap
from app.pipeline.extraction import DuplicateResolutionStrategy

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
        for expected in ("Open File", "Detect Spells", "Extract Selected",
                         "Extract All Pending", "Cancel", "Export", "Settings"):
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
```

- [x] **Step 1.2: Run the tests to confirm they fail**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.main_window'`

- [x] **Step 1.3: Create `app/ui/main_window.py`**

  ```python
  """SpellScribe main application window."""
  from __future__ import annotations

  from pathlib import Path
  from typing import TYPE_CHECKING

  from PySide6.QtCore import Qt
  from PySide6.QtWidgets import (
      QDialog,
      QFileDialog,
      QMainWindow,
      QMessageBox,
      QSplitter,
      QStatusBar,
      QToolBar,
      QWidget,
      QLabel,
      QVBoxLayout,
  )

  if TYPE_CHECKING:
      from app.config import AppConfig
      from app.session import SessionState


  class SpellScribeMainWindow(QMainWindow):
      """Three-panel workbench: document | spell list | review."""

      def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._config = config
          self._session: SessionState | None = None
          self._worker_running = False
          self._active_worker = None
          self._routed_document = None

          self.setWindowTitle("SpellScribe")
          self._build_toolbar()
          self._build_central_widget()
          self._build_status_bar()
          self._update_action_states()

      # ------------------------------------------------------------------
      # Toolbar
      # ------------------------------------------------------------------

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
          # Export pipeline (app/pipeline/export.py) is implemented but the export
          # UI dialog is not yet built. The action is disabled until the dialog exists.
          self._action_export.setToolTip(
              "Export not available in this build — "
              "the export dialog will be added in a future change."
          )
          self._action_export.setEnabled(False)
          self._action_export.triggered.connect(self._on_export)

          tb.addSeparator()

          self._action_settings = tb.addAction("Settings")
          self._action_settings.triggered.connect(self._on_settings)

      def _update_action_states(self) -> None:
          """Enable/disable toolbar actions based on current state."""
          has_session = self._session is not None
          worker_active = self._worker_running

          self._action_open.setEnabled(not worker_active)
          self._action_detect.setEnabled(has_session and not worker_active)
          self._action_extract_selected.setEnabled(has_session and not worker_active)
          self._action_extract_all.setEnabled(has_session and not worker_active)
          self._action_cancel.setEnabled(worker_active)
          self._action_settings.setEnabled(not worker_active)

      # ------------------------------------------------------------------
      # Central widget (placeholder panels)
      # ------------------------------------------------------------------

      def _build_central_widget(self) -> None:
          splitter = QSplitter(Qt.Orientation.Horizontal, self)

          # Left: document panel placeholder
          self._doc_placeholder = QLabel("Open a document to begin.")
          self._doc_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
          splitter.addWidget(self._doc_placeholder)

          # Center: spell list placeholder
          self._list_placeholder = QLabel("No spells detected yet.")
          self._list_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
          splitter.addWidget(self._list_placeholder)

          # Right: review panel placeholder
          self._review_placeholder = QLabel("Select a spell to review.")
          self._review_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
          splitter.addWidget(self._review_placeholder)

          splitter.setSizes([400, 200, 350])
          self.setCentralWidget(splitter)

      def _build_status_bar(self) -> None:
          self._status_bar = QStatusBar(self)
          self.setStatusBar(self._status_bar)

      # ------------------------------------------------------------------
      # Session management
      # ------------------------------------------------------------------

      def _set_session(
          self, session: SessionState, *, source_path: str
      ) -> None:
          """Update internal session state and refresh window title."""
          self._session = session
          filename = Path(source_path).name
          self.setWindowTitle(f"{filename} \u2014 SpellScribe")
          self._update_action_states()

      # ------------------------------------------------------------------
      # Toolbar action handlers (stubs — completed in later tasks)
      # ------------------------------------------------------------------

      def _on_open_file(self) -> None:
          pass  # Implemented in Task 8

      def _on_detect_spells(self) -> None:
          pass  # Implemented in Task 7

      def _on_extract_selected(self) -> None:
          pass  # Implemented in Task 7

      def _on_extract_all(self) -> None:
          pass  # Implemented in Task 7

      def _on_cancel(self) -> None:
          pass  # Implemented in Task 7

      def _on_settings(self) -> None:
          pass  # Implemented in Task 10
  ```

- [x] **Step 1.4: Run tests and confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window -v
  ```
  Expected: All 7 tests pass.

- [x] **Step 1.5: Commit**

  ```pwsh
  git add app/ui/main_window.py tests/test_ui_main_window.py
  git commit -m "feat: add SpellScribeMainWindow shell with toolbar and enable/disable logic"
  ```

---

## Task 2: Document Panel

**Files:**
- Create: `app/ui/document_panel.py`
- Modify: `tests/test_ui_main_window.py` (add document panel tests)

### Step 2.1: Write failing tests for DocumentPanel

Add to `tests/test_ui_main_window.py`:

```python
class TestDocumentPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel(self):
        from app.ui.document_panel import DocumentPanel
        return DocumentPanel()

    def test_panel_shows_placeholder_by_default(self):
        panel = self._make_panel()
        # Placeholder label should be visible; document widget hidden
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
        """display_pdf_page with a real fitz doc renders without error."""
        import fitz
        panel = self._make_panel()
        doc = fitz.open()  # empty in-memory doc
        doc.new_page(width=200, height=300)
        panel.display_pdf_page(doc, page_num=0, highlight_regions=[])
        self.assertFalse(panel._placeholder_label.isVisible())
        doc.close()

    def test_display_pdf_page_with_highlights_calls_get_pixmap_and_does_not_raise(self):
        panel = self._make_panel()
        fitz_doc = MagicMock()
        page = MagicMock()
        fitz_doc.__getitem__ = MagicMock(return_value=page)
        # Valid pixmap data: 10x10 RGB
        pixmap_mock = MagicMock()
        pixmap_mock.width = 10
        pixmap_mock.height = 10
        pixmap_mock.samples = bytes(300)  # 10*10*3
        pixmap_mock.n = 3
        pixmap_mock.stride = 30
        page.get_pixmap.return_value = pixmap_mock
        region = MagicMock()
        region.bbox = (2.0, 3.0, 8.0, 7.0)
        highlight_regions = [region]
        # Must not raise; QPainter highlight drawing loop must execute
        panel.display_pdf_page(fitz_doc, page_num=0, highlight_regions=highlight_regions)
        # PDF was rendered
        page.get_pixmap.assert_called_once()
        # Highlight scroll area content was set (indirect verification that painting occurred)
        self.assertIsNotNone(panel._pdf_scroll.widget())
```

- [ ] **Step 2.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestDocumentPanel -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.document_panel'`

- [x] **Step 2.3: Create `app/ui/document_panel.py`**

  ```python
  """Document viewer panel: PDF rendering and DOCX text display."""
  from __future__ import annotations

  from typing import TYPE_CHECKING

  from PySide6.QtCore import Qt
  from PySide6.QtGui import (
      QColor,
      QImage,
      QPainter,
      QPixmap,
      QTextCharFormat,
      QTextCursor,
  )
  from PySide6.QtWidgets import (
      QLabel,
      QScrollArea,
      QSizePolicy,
      QStackedWidget,
      QTextEdit,
      QVBoxLayout,
      QWidget,
  )

  if TYPE_CHECKING:
      from app.models import TextRegion


  _HIGHLIGHT_COLOR = QColor(255, 220, 50, 120)   # amber, semi-transparent
  _PDF_RENDER_SCALE = 1.5                          # render at 1.5× for clarity


  class DocumentPanel(QWidget):
      """Left panel: displays the current source document with region highlights."""

      def __init__(self, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._build_ui()

      def _build_ui(self) -> None:
          layout = QVBoxLayout(self)
          layout.setContentsMargins(0, 0, 0, 0)

          self._stack = QStackedWidget(self)
          layout.addWidget(self._stack)

          # Page 0 – placeholder
          self._placeholder_label = QLabel("Open a document to begin.")
          self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
          self._stack.addWidget(self._placeholder_label)

          # Page 1 – PDF scroll area with rendered page label
          self._pdf_scroll = QScrollArea()
          self._pdf_scroll.setWidgetResizable(True)
          self._pdf_page_label = QLabel()
          self._pdf_page_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
          self._pdf_page_label.setSizePolicy(
              QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
          )
          self._pdf_scroll.setWidget(self._pdf_page_label)
          self._stack.addWidget(self._pdf_scroll)

          # Page 2 – DOCX read-only text edit
          self._docx_edit = QTextEdit()
          self._docx_edit.setReadOnly(True)
          self._stack.addWidget(self._docx_edit)

          self._stack.setCurrentIndex(0)

      # ------------------------------------------------------------------
      # Public API
      # ------------------------------------------------------------------

      def show_placeholder(self) -> None:
          self._stack.setCurrentWidget(self._placeholder_label)

      def display_pdf_page(
          self,
          fitz_doc: object,
          page_num: int,
          highlight_regions: list[TextRegion],
      ) -> None:
          """Render *page_num* from an open fitz document and overlay highlights."""
          import fitz  # type: ignore[import]

          page: fitz.Page = fitz_doc[page_num]
          mat = fitz.Matrix(_PDF_RENDER_SCALE, _PDF_RENDER_SCALE)
          clip = page.rect
          pix: fitz.Pixmap = page.get_pixmap(matrix=mat, clip=clip)

          img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
          pixmap = QPixmap.fromImage(img)

          if highlight_regions:
              painter = QPainter(pixmap)
              painter.setBrush(_HIGHLIGHT_COLOR)
              painter.setPen(Qt.PenStyle.NoPen)
              for region in highlight_regions:
                  if region.bbox is not None:
                      x0, y0, x1, y1 = (c * _PDF_RENDER_SCALE for c in region.bbox)
                      painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
              painter.end()

          self._pdf_page_label.setPixmap(pixmap)
          self._stack.setCurrentWidget(self._pdf_scroll)

          # Auto-scroll to first highlighted region
          if highlight_regions:
              first = highlight_regions[0]
              if first.bbox is not None:
                  _, y0, _, _ = first.bbox
                  scroll_y = int(y0 * _PDF_RENDER_SCALE)
                  self._pdf_scroll.verticalScrollBar().setValue(scroll_y)

      def display_docx(
          self,
          markdown_text: str,
          highlight_ranges: list[tuple[int, int]],
      ) -> None:
          """Display *markdown_text* in read-only editor; highlight char-offset ranges."""
          self._docx_edit.setPlainText(markdown_text)
          selections: list = []
          if highlight_ranges:
              fmt = QTextCharFormat()
              fmt.setBackground(_HIGHLIGHT_COLOR)
              for start, end in highlight_ranges:
                  cursor = self._docx_edit.textCursor()
                  cursor.setPosition(start)
                  cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                  sel = QTextEdit.ExtraSelection()
                  sel.cursor = cursor
                  sel.format = fmt
                  selections.append(sel)
              # Auto-scroll to first highlight
              first_cursor = self._docx_edit.textCursor()
              first_cursor.setPosition(highlight_ranges[0][0])
              self._docx_edit.setTextCursor(first_cursor)
              self._docx_edit.ensureCursorVisible()

          self._docx_edit.setExtraSelections(selections)
          self._stack.setCurrentWidget(self._docx_edit)
  ```

- [x] **Step 2.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestDocumentPanel -v
  ```
  Expected: All 6 tests pass.

- [x] **Step 2.5: Commit**

  ```pwsh
  git add app/ui/document_panel.py tests/test_ui_main_window.py
  git commit -m "feat: add DocumentPanel with PDF rendering and DOCX highlight support"
  ```

---

## Task 3: Spell List Panel

**Files:**
- Create: `app/ui/spell_list_panel.py`
- Modify: `tests/test_ui_main_window.py`

### Step 3.1: Write failing tests for SpellListPanel

Add to `tests/test_ui_main_window.py`:

```python
class TestSpellListPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_panel(self):
        from app.ui.spell_list_panel import SpellListPanel
        return SpellListPanel()

    def _make_session(self, records):
        """Build a minimal SessionState-like object."""
        session = MagicMock()
        session.records = records
        session.selected_spell_id = None
        return session

    def _make_record(self, spell_id, status_value, name="Magic Missile"):
        from app.session import SpellRecord, SpellRecordStatus
        from app.models import ClassList
        record = MagicMock(spec=SpellRecord)
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
        total = (panel._confirmed_list.count()
                 + panel._needs_review_list.count()
                 + panel._pending_list.count())
        self.assertEqual(total, 0)

    def test_refresh_populates_confirmed_section(self):
        from app.session import SpellRecordStatus
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
```

- [ ] **Step 3.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestSpellListPanel -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.spell_list_panel'`

- [x] **Step 3.3: Create `app/ui/spell_list_panel.py`**

  ```python
  """Three-section spell list panel: Confirmed | Needs Review | Pending."""
  from __future__ import annotations

  from typing import TYPE_CHECKING

  from PySide6.QtCore import Signal
  from PySide6.QtWidgets import (
      QLabel,
      QListWidget,
      QListWidgetItem,
      QVBoxLayout,
      QWidget,
  )

  if TYPE_CHECKING:
      from app.session import SessionState, SpellRecord


  class SpellListPanel(QWidget):
      """Centre panel: three-section spell list driven by SessionState."""

      selected_spell_id_changed = Signal(str)

      def __init__(self, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._id_map: dict[str, str] = {}   # list-item internal id → spell_id
          self._build_ui()

      def _build_ui(self) -> None:
          layout = QVBoxLayout(self)

          layout.addWidget(QLabel("Confirmed"))
          self._confirmed_list = QListWidget()
          self._confirmed_list.itemSelectionChanged.connect(
              lambda: self._on_selection_changed(self._confirmed_list, "confirmed")
          )
          layout.addWidget(self._confirmed_list)

          layout.addWidget(QLabel("Needs Review"))
          self._needs_review_list = QListWidget()
          self._needs_review_list.itemSelectionChanged.connect(
              lambda: self._on_selection_changed(self._needs_review_list, "needs_review")
          )
          layout.addWidget(self._needs_review_list)

          layout.addWidget(QLabel("Pending Extraction"))
          self._pending_list = QListWidget()
          self._pending_list.itemSelectionChanged.connect(
              lambda: self._on_selection_changed(self._pending_list, "pending_extraction")
          )
          layout.addWidget(self._pending_list)

      def refresh(self, session_state: SessionState) -> None:
          """Repopulate all three sections from *session_state.records*."""
          self._confirmed_list.clear()
          self._needs_review_list.clear()
          self._pending_list.clear()

          confirmed = sorted(
              [r for r in session_state.records if r.status.value == "confirmed"],
              key=lambda r: r.section_order,
          )
          needs_review = sorted(
              [r for r in session_state.records if r.status.value == "needs_review"],
              key=lambda r: r.section_order,
          )
          pending = sorted(
              [r for r in session_state.records if r.status.value == "pending_extraction"],
              key=lambda r: r.section_order,
          )

          for record in confirmed:
              self._add_item(self._confirmed_list, record, _record_display_name(record))
          for record in needs_review:
              self._add_item(self._needs_review_list, record, _record_display_name(record))
          for record in pending:
              self._add_item(self._pending_list, record, f"[Pending] {record.spell_id[:8]}")

      # ------------------------------------------------------------------
      # Internals
      # ------------------------------------------------------------------

      def _add_item(self, list_widget: QListWidget, record: SpellRecord, label: str) -> None:
          item = QListWidgetItem(label)
          item.setData(256, record.spell_id)   # store spell_id in UserRole
          list_widget.addItem(item)

      def _on_selection_changed(self, source_list: QListWidget, _section: str) -> None:
          items = source_list.selectedItems()
          if not items:
              return
          spell_id: str = items[0].data(256)
          # Deselect other lists
          for other in (self._confirmed_list, self._needs_review_list, self._pending_list):
              if other is not source_list:
                  other.clearSelection()
          self.selected_spell_id_changed.emit(spell_id)


  def _record_display_name(record: SpellRecord) -> str:
      spell = record.draft_spell or record.canonical_spell
      if spell is not None:
          return spell.name
      return f"[{record.spell_id[:8]}]"
  ```

- [x] **Step 3.4: Run tests and confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestSpellListPanel -v
  ```
  Expected: All 5 tests pass.

- [x] **Step 3.5: Commit**

  ```pwsh
  git add app/ui/spell_list_panel.py tests/test_ui_main_window.py
  git commit -m "feat: add SpellListPanel with three-section layout and selection signal"
  ```

---

## Task 4: Review Panel — Pending Status View and Review Editor Seeding

**Files:**
- Create: `app/ui/review_panel.py`
- Modify: `tests/test_ui_main_window.py`

### Step 4.1: Write failing tests for ReviewPanel

Add to `tests/test_ui_main_window.py`:

```python
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
        from app.session import SpellRecord, SpellRecordStatus
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
        # Pending view is visible; placeholder and editor are not
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
        # Verify guard: _loading=True suppresses apply_review_edits (e.g. during setPlainText in show_review_record)
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
```

- [ ] **Step 4.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestReviewPanel -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.review_panel'`

- [x] **Step 4.3: Create `app/ui/review_panel.py`**

  ```python
  """Right-side panel: pending status view or review editor."""
  from __future__ import annotations

  from typing import TYPE_CHECKING, Any

  from PySide6.QtCore import Qt, Signal
  from PySide6.QtWidgets import (
      QCheckBox,
      QComboBox,
      QDialog,
      QDialogButtonBox,
      QFormLayout,
      QInputDialog,
      QLabel,
      QLineEdit,
      QMessageBox,
      QPushButton,
      QRadioButton,
      QScrollArea,
      QSizePolicy,
      QStackedWidget,
      QTextEdit,
      QVBoxLayout,
      QWidget,
  )

  from app.pipeline.extraction import (
      DuplicateResolutionStrategy,
      accept_review_record,
      apply_review_edits,
      delete_record,
      discard_record_draft,
      get_confirmed_save_duplicate_conflict,
      get_review_draft,
      reextract_record_into_draft,
      save_confirmed_changes,
  )

  if TYPE_CHECKING:
      from app.config import AppConfig
      from app.models import Spell
      from app.session import SessionState, SpellRecord


  class ReviewPanel(QWidget):
      """Right-side panel that shows pending-status info or the review editor."""

      # Emitted when the session changes and the spell list needs refreshing
      session_changed = Signal(object)   # carries updated SessionState

      def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._config = config
          self._current_record: SpellRecord | None = None
          self._current_session: SessionState | None = None
          self._loading = False
          self._build_ui()

      # ------------------------------------------------------------------
      # UI Construction
      # ------------------------------------------------------------------

      def _build_ui(self) -> None:
          layout = QVBoxLayout(self)
          layout.setContentsMargins(0, 0, 0, 0)

          self._stack = QStackedWidget(self)
          layout.addWidget(self._stack)

          # Page 0 – placeholder
          self._placeholder_label = QLabel("Select a spell to review.")
          self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
          self._stack.addWidget(self._placeholder_label)

          # Page 1 – pending status view
          self._pending_widget = self._build_pending_widget()
          self._stack.addWidget(self._pending_widget)

          # Page 2 – review editor
          self._review_widget = self._build_review_widget()
          self._stack.addWidget(self._review_widget)

          self._stack.setCurrentWidget(self._placeholder_label)

      def _build_pending_widget(self) -> QWidget:
          w = QWidget()
          layout = QVBoxLayout(w)
          layout.addWidget(QLabel("<b>Pending Extraction</b>"))
          self._pending_name_label = QLabel()
          self._pending_order_label = QLabel()
          self._pending_range_label = QLabel()
          layout.addWidget(self._pending_name_label)
          layout.addWidget(self._pending_order_label)
          layout.addWidget(self._pending_range_label)
          layout.addStretch()
          return w

      def _build_review_widget(self) -> QWidget:
          container = QWidget()
          outer = QVBoxLayout(container)

          # Dirty indicator banner
          self._dirty_banner = QLabel("⚠ Unsaved changes")
          self._dirty_banner.setStyleSheet("background: #ffe082; padding: 4px;")
          self._dirty_banner.setVisible(False)
          outer.addWidget(self._dirty_banner)

          # Scrollable form
          scroll = QScrollArea()
          scroll.setWidgetResizable(True)
          form_widget = QWidget()
          self._form_layout = QFormLayout(form_widget)
          scroll.setWidget(form_widget)
          outer.addWidget(scroll)

          # Review editor fields
          self._field_name = QLineEdit()
          self._field_level = QLineEdit()
          self._field_description = QTextEdit()
          self._form_layout.addRow("Name:", self._field_name)
          self._form_layout.addRow("Level:", self._field_level)
          self._form_layout.addRow("Description:", self._field_description)
          self._field_name.editingFinished.connect(self._on_field_edited)
          self._field_level.editingFinished.connect(self._on_field_edited)
          self._field_description.textChanged.connect(self._on_field_edited)

          self._field_class_list = QComboBox()
          self._field_class_list.addItems(["Wizard", "Priest"])
          self._form_layout.addRow("Class:", self._field_class_list)

          self._field_school = QLineEdit()
          self._form_layout.addRow("School(s):", self._field_school)

          self._field_sphere = QLineEdit()
          self._form_layout.addRow("Sphere(s):", self._field_sphere)

          self._field_range = QLineEdit()
          self._form_layout.addRow("Range:", self._field_range)

          self._field_casting_time = QLineEdit()
          self._form_layout.addRow("Casting Time:", self._field_casting_time)

          self._field_duration = QLineEdit()
          self._form_layout.addRow("Duration:", self._field_duration)

          self._field_area_of_effect = QLineEdit()
          self._form_layout.addRow("Area of Effect:", self._field_area_of_effect)

          self._field_saving_throw = QLineEdit()
          self._form_layout.addRow("Saving Throw:", self._field_saving_throw)

          self._field_components = QLineEdit()
          self._form_layout.addRow("Components:", self._field_components)

          self._field_reversible = QCheckBox()
          self._form_layout.addRow("Reversible:", self._field_reversible)

          self._field_needs_review = QCheckBox()
          self._form_layout.addRow("Needs Review:", self._field_needs_review)

          self._field_review_notes = QTextEdit()
          self._field_review_notes.setMaximumHeight(80)
          self._form_layout.addRow("Review Notes:", self._field_review_notes)

          # Note: `_field_description.textChanged` IS connected (see above). Spurious
          # `apply_review_edits` calls during `setPlainText()` in `show_review_record` are
          # prevented by the `self._loading` flag — `_on_field_edited` returns immediately
          # when `_loading=True`.
          self._field_school.editingFinished.connect(self._on_field_edited)
          self._field_sphere.editingFinished.connect(self._on_field_edited)
          self._field_range.editingFinished.connect(self._on_field_edited)
          self._field_casting_time.editingFinished.connect(self._on_field_edited)
          self._field_duration.editingFinished.connect(self._on_field_edited)
          self._field_area_of_effect.editingFinished.connect(self._on_field_edited)
          self._field_saving_throw.editingFinished.connect(self._on_field_edited)
          self._field_components.editingFinished.connect(self._on_field_edited)
          self._field_reversible.stateChanged.connect(self._on_field_edited)
          self._field_needs_review.stateChanged.connect(self._on_field_edited)
          self._field_review_notes.textChanged.connect(self._on_field_edited)

          # Action buttons
          self._btn_save = QPushButton("Save Confirmed")
          self._btn_accept = QPushButton("Accept (Needs Review)")
          self._btn_reextract = QPushButton("Re-extract…")
          self._btn_discard = QPushButton("Discard Draft")
          self._btn_delete = QPushButton("Delete")

          self._btn_save.clicked.connect(self._on_save_confirmed)
          self._btn_accept.clicked.connect(self._on_accept)
          self._btn_reextract.clicked.connect(self._on_reextract)
          self._btn_discard.clicked.connect(self._on_discard)
          self._btn_delete.clicked.connect(self._on_delete)

          for btn in (self._btn_save, self._btn_accept, self._btn_reextract,
                      self._btn_discard, self._btn_delete):
              outer.addWidget(btn)

          return container

      # ------------------------------------------------------------------
      # Public API
      # ------------------------------------------------------------------

      def show_placeholder(self) -> None:
          self._current_record = None
          self._stack.setCurrentWidget(self._placeholder_label)

      def show_pending_record(self, record: SpellRecord) -> None:
          self._current_record = record
          spell = record.draft_spell or record.canonical_spell
          name = spell.name if spell else f"[{record.spell_id[:8]}]"
          self._pending_name_label.setText(f"Spell: {name}")
          self._pending_order_label.setText(f"Discovery order: {record.extraction_order}")
          self._pending_range_label.setText(
              f"Lines: {record.boundary_start_line}–{record.boundary_end_line}"
          )
          self._stack.setCurrentWidget(self._pending_widget)

      def show_review_record(
          self, record: SpellRecord, session_state: SessionState
      ) -> None:
          self._loading = True
          self._current_record = record
          self._current_session = session_state
          draft: Spell = get_review_draft(record)

          self._field_name.setText(draft.name)
          self._field_level.setText(str(draft.level))
          self._field_description.setPlainText(draft.description)
          self._field_class_list.setCurrentText(draft.class_list if isinstance(draft.class_list, str) else draft.class_list.value)
          self._field_school.setText(", ".join(draft.school) if draft.school else "")
          self._field_sphere.setText(", ".join(draft.sphere) if draft.sphere else "")
          self._field_range.setText(draft.range)
          self._field_casting_time.setText(draft.casting_time)
          self._field_duration.setText(draft.duration)
          self._field_area_of_effect.setText(draft.area_of_effect)
          self._field_saving_throw.setText(draft.saving_throw)
          self._field_components.setText(", ".join(c if isinstance(c, str) else c.value for c in draft.components))
          self._field_reversible.setChecked(draft.reversible)
          self._field_needs_review.setChecked(draft.needs_review)
          # Always use `draft.review_notes or ''` not `draft.review_notes` directly,
          # since the field can be None.
          self._field_review_notes.setPlainText(draft.review_notes or "")

          self._dirty_banner.setVisible(record.draft_dirty)
          self._btn_accept.setVisible(record.status.value == "needs_review")
          self._btn_save.setVisible(record.status.value == "confirmed")
          self._loading = False

          self._stack.setCurrentWidget(self._review_widget)

      # ------------------------------------------------------------------
      # Action handlers (implemented in Task 5)
      # ------------------------------------------------------------------

      def _on_save_confirmed(self) -> None:
          pass  # Implemented in Task 5

      def _on_accept(self) -> None:
          pass  # Implemented in Task 5

      def _on_reextract(self) -> None:
          pass  # Implemented in Task 5

      def _on_discard(self) -> None:
          pass  # Implemented in Task 5

      def _on_delete(self) -> None:
          pass  # Implemented in Task 5

      def _on_field_edited(self) -> None:
          if self._loading:
              return
          if self._current_record is None:
              return
          updates = {
              "name": self._field_name.text().strip(),
              "level": self._field_level.text().strip(),
              "description": self._field_description.toPlainText().strip(),
              "class_list": self._field_class_list.currentText(),
              "school": [s.strip() for s in self._field_school.text().split(",") if s.strip()],
              "sphere": [s.strip() for s in self._field_sphere.text().split(",") if s.strip()] or None,
              "range": self._field_range.text().strip(),
              "casting_time": self._field_casting_time.text().strip(),
              "duration": self._field_duration.text().strip(),
              "area_of_effect": self._field_area_of_effect.text().strip(),
              "saving_throw": self._field_saving_throw.text().strip(),
              "components": [c.strip() for c in self._field_components.text().split(",") if c.strip()],
              "reversible": self._field_reversible.isChecked(),
              "needs_review": self._field_needs_review.isChecked(),
              "review_notes": self._field_review_notes.toPlainText().strip() or None,
          }
          try:
              apply_review_edits(self._current_record, draft_updates=updates, config=self._config)
              self._dirty_banner.setVisible(True)
              self._dirty_banner.setText("Unsaved changes")
          except Exception as exc:
              self._dirty_banner.setVisible(True)
              self._dirty_banner.setText(f"Invalid: {exc}")
  ```

  > **Note:** `QVBoxLayout`, `QRadioButton`, and `QDialogButtonBox` must all be imported at module level in `review_panel.py` (not locally inside `_on_accept`) so they can be patched in tests.

- [x] **Step 4.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestReviewPanel -v
  ```
  Expected: All 7 tests pass.

- [x] **Step 4.5: Commit**

  ```pwsh
  git add app/ui/review_panel.py tests/test_ui_main_window.py
  git commit -m "feat: add ReviewPanel with pending status view and review editor skeleton"
  ```

---

## Task 5: Review Editor Action Buttons

**Files:**
- Modify: `app/ui/review_panel.py`
- Modify: `tests/test_ui_main_window.py`

### Step 5.1: Write failing tests for review action buttons

Add to `tests/test_ui_main_window.py`:

```python
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
        with patch("app.ui.review_panel.get_confirmed_save_duplicate_conflict",
                   return_value=conflict), \
             patch("app.ui.review_panel.save_confirmed_changes") as mock_save, \
             patch("app.ui.review_panel.QMessageBox") as mock_mb:
            panel._on_save_confirmed()
            mock_mb.warning.assert_called_once()
            mock_save.assert_not_called()
        self.assertEqual(emitted, [])

    def test_save_proceeds_when_no_conflict(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.get_confirmed_save_duplicate_conflict", return_value=None), \
             patch("app.ui.review_panel.save_confirmed_changes", return_value=record) as mock_save:
            panel._on_save_confirmed()
            mock_save.assert_called_once()
        self.assertEqual(len(emitted), 1)

    def test_discard_calls_discard_and_clears_dirty(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.draft_dirty = True
        panel._dirty_banner.setVisible(True)
        with patch("app.ui.review_panel.discard_record_draft") as mock_discard, \
             patch.object(panel, "show_review_record") as mock_show:
            panel._on_discard()
            mock_discard.assert_called_once_with(record)
            mock_show.assert_called_once_with(panel._current_record, panel._current_session)
        self.assertFalse(panel._dirty_banner.isVisible())

    def test_delete_calls_delete_and_emits_session_changed_on_confirm(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes) as mock_q, \
             patch("app.ui.review_panel.delete_record",
                   return_value=True) as mock_del:
            panel._on_delete()
            mock_del.assert_called_once_with(session, spell_id="abc-123")
        self.assertGreater(len(emitted), 0, "session_changed should have been emitted after delete")

    def test_delete_aborted_when_user_cancels(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        with patch("app.ui.review_panel.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No), \
             patch("app.ui.review_panel.delete_record") as mock_del:
            panel._on_delete()
            mock_del.assert_not_called()

    def test_reextract_no_op_on_empty_focus_prompt_cancel(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        with patch("app.ui.review_panel.QInputDialog.getText",
                   return_value=("", False)), \
             patch("app.ui.review_panel.reextract_record_into_draft") as mock_re:
            panel._on_reextract()
            mock_re.assert_not_called()

    def test_reextract_calls_api_when_user_provides_prompt(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        updated_spell = MagicMock()
        updated_spell.name = "Fireball v2"
        updated_spell.level = 3
        updated_spell.description = "Even bigger"
        updated_spell.review_notes = None
        with patch("app.ui.review_panel.QInputDialog.getText",
                   return_value=("focus on damage", True)), \
             patch("app.ui.review_panel.reextract_record_into_draft",
                   return_value=updated_spell) as mock_re, \
             patch("app.ui.review_panel.get_review_draft", return_value=updated_spell):
            panel._on_reextract()
            mock_re.assert_called_once_with(
                session, spell_id="abc-123",
                focus_prompt="focus on damage",
                config=panel._config,
            )
            self.assertEqual(panel._field_name.text(), updated_spell.name)

    def test_accept_non_conflicting_record_commits_and_emits_session_changed(self):
        from app.ui.review_panel import ReviewPanel, DuplicateResolutionStrategy
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

    def test_accept_conflict_skip_leaves_record_uncommitted(self):
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        spell = record.draft_spell
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        # First call (SKIP attempt) returns False (conflict exists)
        # Dialog exec returns Rejected (user cancels), so no further commit
        with patch("app.ui.review_panel.accept_review_record", return_value=False), \
             patch.object(panel.__class__, "_on_accept", wraps=panel._on_accept):
            with patch("app.ui.review_panel.QDialog") as mock_dlg_cls, \
                 patch("app.ui.review_panel.QVBoxLayout"), \
                 patch("app.ui.review_panel.QRadioButton"), \
                 patch("app.ui.review_panel.QDialogButtonBox"):
                mock_dlg_cls.DialogCode = QDialog.DialogCode
                mock_dlg_cls.return_value = MagicMock()
                mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
                panel._on_accept()
        self.assertEqual(emitted, [], "session_changed should not be emitted when dialog is cancelled")

    def test_accept_conflict_dialog_accepted_overwrite_calls_overwrite_strategy(self):
        """When conflict dialog is accepted and OVERWRITE radio is checked, calls accept with OVERWRITE."""
        with patch("app.ui.review_panel.accept_review_record") as mock_accept, \
             patch("app.ui.review_panel.QDialog") as mock_dlg_cls, \
             patch("app.ui.review_panel.QVBoxLayout"), \
             patch("app.ui.review_panel.QRadioButton"), \
             patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.DialogCode = QDialog.DialogCode
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_accept.side_effect = [False, True]
            panel, record, session = self._make_panel_with_confirmed_record()
            record.status = MagicMock(value="needs_review")
            # Default radio is rb_overwrite (first radio = checked by default)
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 2)
        self.assertEqual(mock_accept.call_args_list[1].kwargs["duplicate_resolution"], DuplicateResolutionStrategy.OVERWRITE)

    def test_accept_conflict_dialog_rejected_leaves_record_uncommitted(self):
        """When conflict dialog is dismissed (Rejected), record stays uncommitted."""
        with patch("app.ui.review_panel.accept_review_record") as mock_accept, \
             patch("app.ui.review_panel.QDialog") as mock_dlg_cls, \
             patch("app.ui.review_panel.QVBoxLayout"), \
             patch("app.ui.review_panel.QRadioButton"), \
             patch("app.ui.review_panel.QDialogButtonBox"):
            mock_dlg_cls.DialogCode = QDialog.DialogCode
            mock_dlg_cls.return_value = MagicMock()
            mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            mock_accept.return_value = False
            panel, record, session = self._make_panel_with_confirmed_record()
            record.status = MagicMock(value="needs_review")
            panel._on_accept()
        self.assertEqual(mock_accept.call_count, 1)

    def test_accept_conflict_dialog_accepted_calls_accept_review_record_second_time(self):
        """When conflict dialog is accepted (any strategy), accept_review_record is called again."""
        panel, record, session = self._make_panel_with_confirmed_record()
        record.status = MagicMock(value="needs_review")
        spell = record.draft_spell
        with patch("app.ui.review_panel.get_review_draft", return_value=spell):
            panel.show_review_record(record, session)
        call_count = [0]
        def mock_accept(*args, **kwargs):
            call_count[0] += 1
            return call_count[0] > 1  # First SKIP returns False, second (resolution) returns True
        emitted = []
        panel.session_changed.connect(lambda s: emitted.append(s))
        with patch("app.ui.review_panel.accept_review_record", side_effect=mock_accept):
            with patch("app.ui.review_panel.QDialog") as mock_dlg_cls, \
                 patch("app.ui.review_panel.QVBoxLayout"), \
                 patch("app.ui.review_panel.QRadioButton"), \
                 patch("app.ui.review_panel.QDialogButtonBox"):
                mock_dlg_cls.DialogCode = QDialog.DialogCode
                mock_dlg_cls.return_value = MagicMock()
                mock_dlg_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
                panel._on_accept()
        # accept_review_record called twice (once SKIP, once with resolution strategy)
        self.assertEqual(call_count[0], 2)
        self.assertGreater(len(emitted), 0, "session_changed emitted after successful accept")
```

> **Test limitation — radio button selection:** The conflict-resolution dialog tests patch
> `QRadioButton` to prevent C++ type enforcement issues. As a consequence, `isChecked()`
> always returns a truthy `MagicMock`, so all four tests exercise the OVERWRITE branch.
> The KEEP_BOTH and Skip branches require integration testing with `QT_QPA_PLATFORM=offscreen`
> and real radio button objects — deferred to a follow-up test pass.

- [ ] **Step 5.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestReviewPanelActions -v
  ```
  Expected: FAIL — test_accept_non_conflicting_record_commits_and_emits_session_changed fails because _on_accept is a stub.

- [x] **Step 5.3: Implement review action handlers in `app/ui/review_panel.py`**

  Replace the five stub action handler methods:

  ```python
  def _on_save_confirmed(self) -> None:
      if self._current_record is None or self._current_session is None:
          return
      conflict = get_confirmed_save_duplicate_conflict(
          self._current_session, spell_id=self._current_record.spell_id
      )
      if conflict is not None:
          QMessageBox.warning(
              self,
              "Duplicate Spell",
              f"A confirmed spell named '{conflict.canonical_spell.name}' already exists. "
              "Resolve the duplicate before saving.",
          )
          return
      save_confirmed_changes(
          self._current_session,
          spell_id=self._current_record.spell_id,
          config=self._config,
      )
      self._dirty_banner.setVisible(False)
      self.session_changed.emit(self._current_session)

  def _on_accept(self) -> None:
      if self._current_record is None or self._current_session is None:
          return
      # Try commit with SKIP — succeeds if no conflict exists
      committed = accept_review_record(
          self._current_session,
          spell_id=self._current_record.spell_id,
          duplicate_resolution=DuplicateResolutionStrategy.SKIP,
          config=self._config,
      )
      if committed:
          self.session_changed.emit(self._current_session)
          return
      # Conflict: show resolution dialog
      dlg = QDialog(self)
      dlg.setWindowTitle("Duplicate Spell — Choose Resolution")
      layout = QVBoxLayout(dlg)
      layout.addWidget(QLabel("A confirmed spell with the same name already exists."))
      rb_overwrite = QRadioButton("Overwrite existing confirmed spell")
      rb_keep_both = QRadioButton("Keep both (rename to avoid conflict)")
      rb_overwrite.setChecked(True)
      layout.addWidget(rb_overwrite)
      layout.addWidget(rb_keep_both)
      rb_skip = QRadioButton("Skip — leave in Needs Review (do not commit)")
      layout.addWidget(rb_skip)
      buttons = QDialogButtonBox(
          QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
      )
      buttons.accepted.connect(dlg.accept)
      buttons.rejected.connect(dlg.reject)
      layout.addWidget(buttons)
      if dlg.exec() != QDialog.DialogCode.Accepted:
          return
      if rb_overwrite.isChecked():
          strategy = DuplicateResolutionStrategy.OVERWRITE
      elif rb_keep_both.isChecked():
          strategy = DuplicateResolutionStrategy.KEEP_BOTH
      else:
          # rb_skip: leave in needs_review without committing
          return
      accept_review_record(
          self._current_session,
          spell_id=self._current_record.spell_id,
          duplicate_resolution=strategy,
          config=self._config,
      )
      self.session_changed.emit(self._current_session)

  def _on_reextract(self) -> None:
      if self._current_record is None or self._current_session is None:
          return
      focus_prompt, ok = QInputDialog.getText(
          self,
          "Re-extract Spell",
          "Enter an optional focus prompt for the LLM:",
      )
      if not ok:
          return
      updated_spell = reextract_record_into_draft(
          self._current_session,
          spell_id=self._current_record.spell_id,
          focus_prompt=focus_prompt,
          config=self._config,
      )
      # Refresh all editor fields with new draft
      self.show_review_record(self._current_record, self._current_session)
      self._dirty_banner.setVisible(True)

  def _on_discard(self) -> None:
      if self._current_record is None:
          return
      if self._current_session is None:
          return
      discard_record_draft(self._current_record)
      self._dirty_banner.setVisible(False)
      self.show_review_record(self._current_record, self._current_session)
      self.session_changed.emit(self._current_session)

  def _on_delete(self) -> None:
      if self._current_record is None or self._current_session is None:
          return
      answer = QMessageBox.question(
          self,
          "Delete Spell",
          f"Delete this spell record? This cannot be undone.",
      )
      if answer != QMessageBox.StandardButton.Yes:
          return
      delete_record(self._current_session, spell_id=self._current_record.spell_id)
      self._current_record = None
      self.show_placeholder()
      self.session_changed.emit(self._current_session)
  ```

  > **Note:** `QDialog`, `QDialogButtonBox`, `QInputDialog`, and `QMessageBox` are already imported at module level in Task 4.3's `review_panel.py` imports. No additional import needed here.

- [x] **Step 5.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestReviewPanelActions -v
  ```
  Expected: All 12 tests pass.

- [ ] **Step 5.5: Run the full test suite to check for regressions**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest discover tests/ -v
  ```
  Expected: All existing tests still pass; new tests pass.

- [x] **Step 5.6: Commit**

  ```pwsh
  git add app/ui/review_panel.py tests/test_ui_main_window.py
  git commit -m "feat: implement review editor action buttons (save, accept, re-extract, discard, delete)"
  ```

---

## Task 6: QThread Workers and Cancel

**Files:**
- Create: `app/ui/workers.py`
- Modify: `tests/test_ui_main_window.py`

### Step 6.1: Write failing tests for workers

Add to `tests/test_ui_main_window.py`:

```python
class TestWorkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def test_detect_worker_emits_spells_detected_on_success(self):
        from app.ui.workers import DetectSpellsWorker
        import threading

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
        from app.ui.workers import DetectSpellsWorker
        import threading

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
        from app.ui.workers import DetectSpellsWorker
        import threading

        cancel = threading.Event()
        cancel.set()   # already cancelled
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
        from app.ui.workers import ExtractWorker
        import threading

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
        from app.ui.workers import DetectSpellsWorker
        import threading
        result_session = MagicMock()
        result_session.records = []
        worker = DetectSpellsWorker(routed_document=MagicMock(), config=MagicMock(), session_state=MagicMock(), cancel_event=threading.Event())
        sessions = []
        worker.session_ready.connect(lambda s: sessions.append(s))
        with patch("app.ui.workers.detect_spells", return_value=result_session):
            worker.run()
        self.assertEqual(sessions, [result_session])

    def test_extract_worker_emits_extraction_complete_with_result(self):
        from app.ui.workers import ExtractWorker
        import threading
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
        from app.ui.workers import ExtractWorker
        import threading
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
        with patch("app.ui.workers.extract_selected_pending",
                   return_value=result_session) as mock_sel, \
             patch("app.ui.workers.extract_all_pending") as mock_all:
            worker.run()
            mock_sel.assert_called_once()
            mock_all.assert_not_called()

    def test_extract_worker_cancelled_before_start_does_not_call_extract(self):
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
        """Spec: cancel drops only the in-flight record, preserving all others.
        DEFERRED — extract_all_pending is a single blocking call with no per-record
        checkpoint; the batch always runs to completion once started.
        Full-batch completion preservation (emit result before cancelled) IS implemented.
        See out-of-scope note in Task 6.
        """
        self.skipTest(
            "Per-record mid-batch cancellation requires refactoring "
            "extract_all_pending with a streaming/callback API; see out-of-scope note in Task 6."
        )

    def test_extract_worker_cancelled_after_extraction_emits_both_signals(self):
        """Cancel set during extraction still delivers completed results."""
        session = MagicMock()
        config = MagicMock()
        cancel_event = threading.Event()
        result_session = MagicMock()
        complete_calls = []
        cancelled_calls = []
        def fake_extract(session_state, config):
            cancel_event.set()  # simulate cancel firing mid-extraction
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
        self.assertEqual(cancelled_calls, [True])

    def test_detect_worker_forwards_session_state_to_detect_spells(self):
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

    def test_detect_worker_cancelled_after_detection_emits_session_ready_then_cancelled(self):
        """Post-detection cancel still delivers results before emitting cancelled."""
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
        self.assertEqual(cancelled_calls, [True])
```

- [x] **Step 6.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestWorkers -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.workers'`

- [x] **Step 6.3: Create `app/ui/workers.py`**

  ```python
  """QObject-based workers for background extraction jobs."""
  from __future__ import annotations

  import threading
  from typing import TYPE_CHECKING, Literal

  from PySide6.QtCore import QObject, Signal

  from app.pipeline.extraction import (
      detect_spells,
      extract_all_pending,
      extract_selected_pending,
  )

  if TYPE_CHECKING:
      from app.config import AppConfig
      from app.pipeline.ingestion import RoutedDocument
      from app.session import SessionState


  class DetectSpellsWorker(QObject):
      """Runs detect_spells() on a background QThread."""

      spells_detected = Signal(int)       # emitted on success: number of pending records
      session_ready = Signal(object)      # emitted on success: the new SessionState
      progress_updated = Signal(int, int) # (current, total)
      cancelled = Signal()
      failed = Signal(str, str)           # (title, message)

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
          try:
              result = detect_spells(self._routed_document, config=self._config, session_state=self._session_state)
          except Exception as exc:  # noqa: BLE001
              self.failed.emit("Detection Failed", str(exc))
              return
          if self._cancel_event.is_set():
              self.session_ready.emit(result)
              pending_count = sum(1 for r in result.records if r.status.value == "pending_extraction")
              self.spells_detected.emit(pending_count)
              self.cancelled.emit()
              return
          pending_count = sum(
              1 for r in result.records if r.status.value == "pending_extraction"
          )
          self.session_ready.emit(result)
          self.spells_detected.emit(pending_count)


  class ExtractWorker(QObject):
      """Runs extract_all_pending() or extract_selected_pending() on a background QThread.

      Note: cancel is checked before and after the full extraction run.
      Per-record interruptibility requires a future streaming Stage 2 API.
      """

      record_extracted = Signal(str)      # spell_id of each newly-extracted record
      extraction_complete = Signal(object) # emitted once at end of run: updated SessionState
      progress_updated = Signal(int, int) # (completed, total)
      cancelled = Signal()
      failed = Signal(str, str)           # (title, message)

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
              self.cancelled.emit()
              return
          pending_before = {
              r.spell_id for r in self._session_state.records
              if r.status.value == "pending_extraction"
          }
          try:
              if self._mode == "all":
                  result = extract_all_pending(self._session_state, config=self._config)
              else:
                  result = extract_selected_pending(self._session_state, config=self._config)
          except Exception as exc:
              self.failed.emit("Extraction Failed", str(exc))
              return
          if self._cancel_event.is_set():
              # Still emit completed work so it isn't lost
              self.extraction_complete.emit(result)
              self.cancelled.emit()
              return
          processed_ids = {
              r.spell_id for r in result.records
              if r.status.value != "pending_extraction"
              and r.spell_id in pending_before
          }
          for spell_id in processed_ids:
              self.record_extracted.emit(spell_id)
          self.extraction_complete.emit(result)
  ```

> **Out of scope — "Cancel preserves completed work" (desktop-workbench spec scenario):**
> The `cancel_event` is checked before and after the entire `extract_all_pending` call.
> Cancellation that fires **after** the call returns preserves all completed records —
> `extraction_complete` is still emitted before `cancelled`. Cancellation that fires
> **before** the call starts skips extraction entirely (no records emitted).
> The truly unsupported scenario is **"drops only the in-flight record"** (mid-record
> cancellation): there is no per-record checkpoint inside `extract_all_pending`, so
> the batch always runs to completion once started. Per-record interruptibility
> requires a future architectural refactor of the extraction pipeline.
> Tracked in `test_cancel_mid_record_drops_only_inflight_record_deferred` (skipTest).
> This deviation should be reflected in a spec amendment to the desktop-workbench spec.
> The current spec text does not match the implemented behavior.

- [x] **Step 6.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestWorkers -v
  ```
  Expected: All 9 tests pass.

- [x] **Step 6.5: Commit**

  ```pwsh
  git add app/ui/workers.py tests/test_ui_main_window.py
  git commit -m "feat: add DetectSpellsWorker and ExtractWorker with typed signals and cancel support"
  ```

---

## Task 7: Worker Integration into Main Window and Status Bar

**Files:**
- Modify: `app/ui/main_window.py`
- Modify: `tests/test_ui_main_window.py`

### Step 7.1: Write failing tests for worker orchestration

Add to `tests/test_ui_main_window.py`:

```python
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
        with patch("app.ui.main_window.QThread") as mock_thread_cls, \
             patch("app.ui.main_window.DetectSpellsWorker") as mock_worker_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker
            win._on_detect_spells()
            # Actions should be disabled while worker is "active"
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
        # Add a spell_list_panel mock attribute
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
        with patch("app.ui.main_window.QThread") as mock_thread_cls, \
             patch("app.ui.main_window.ExtractWorker") as mock_worker_cls:
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
        win._on_extraction_complete(updated_session)
        self.assertNotEqual(win._status_bar.currentMessage(), "")
```

- [x] **Step 7.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowWorkers -v
  ```
  Expected: Tests fail because `_on_detect_spells` etc. are stubs.

- [x] **Step 7.3: Implement worker orchestration in `app/ui/main_window.py`**

  Add these imports to `app/ui/main_window.py`:
  ```python
  import threading

  from PySide6.QtCore import QThread

  from app.ui.workers import DetectSpellsWorker, ExtractWorker
  ```

  Add to `SpellScribeMainWindow.__init__` (after existing init lines):
  ```python
  self._cancel_event: threading.Event = threading.Event()
  self._active_thread: QThread | None = None
  self._active_worker: object = None
  ```

  Replace the stub action handlers `_on_detect_spells`, `_on_extract_selected`, `_on_extract_all`, `_on_cancel`, `_on_export` with:

  ```python
  def _on_detect_spells(self) -> None:
      if self._session is None or self._routed_document is None:
          return
      self._cancel_event = threading.Event()
      worker = DetectSpellsWorker(
          routed_document=self._routed_document,
          config=self._config,
          session_state=self._session,  # ← pass existing session
          cancel_event=self._cancel_event,
      )
      thread = QThread(self)
      worker.moveToThread(thread)
      worker.session_ready.connect(self._on_session_ready)
      worker.spells_detected.connect(self._on_spells_detected)
      worker.failed.connect(self._on_worker_failed)
      worker.cancelled.connect(self._on_worker_cancelled)
      thread.started.connect(worker.run)
      thread.finished.connect(thread.deleteLater)
      self._active_thread = thread
      self._worker_running = True
      self._update_action_states()
      self._active_worker = worker
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
      thread.started.connect(worker.run)
      thread.finished.connect(thread.deleteLater)
      self._active_thread = thread
      self._worker_running = True
      self._update_action_states()
      self._active_worker = worker
      thread.start()

  def _on_cancel(self) -> None:
      # Note: cancel is checked before and after the full extraction run.
      # Per-record interruptibility requires a future streaming Stage 2 API.
      self._cancel_event.set()

  def _on_spells_detected(self, count: int) -> None:
      self._worker_running = False
      self._update_action_states()
      self._status_bar.showMessage(f"Detection complete — {count} spell(s) pending extraction.")
      if hasattr(self, "_spell_list_panel") and self._session is not None:
          self._spell_list_panel.refresh(self._session)

  def _on_record_extracted(self, spell_id: str) -> None:
      self._status_bar.showMessage(f"Extracted: {spell_id}")
      # Note: self._session is not yet updated per-record during extraction.
      # The list refresh here shows stale status for in-progress records.
      # This is acceptable — the final _on_extraction_complete refreshes with the full updated session.
      self._update_action_states()

  def _on_extraction_complete(self, updated_session: SessionState) -> None:
      self._session = updated_session
      self._worker_running = False
      self._update_action_states()
      extracted_count = sum(
          1 for r in updated_session.records
          if r.status.value != "pending_extraction"
      )
      self._status_bar.showMessage(
          f"Extraction complete — {extracted_count} spell(s) extracted."
      )
      if hasattr(self, "_spell_list_panel") and self._session is not None:
          self._spell_list_panel.refresh(updated_session)

  def _on_worker_failed(self, title: str, message: str) -> None:
      from PySide6.QtWidgets import QMessageBox
      self._worker_running = False
      self._update_action_states()
      QMessageBox.critical(self, title, message)

  def _on_worker_cancelled(self) -> None:
      self._worker_running = False
      self._update_action_states()
      self._status_bar.showMessage("Operation cancelled.")

  def _on_session_ready(self, new_session: SessionState) -> None:
      self._session = new_session

  def _on_export(self) -> None:
      # TODO: Launch export dialog when add-export-capabilities UI is integrated.
      from PySide6.QtWidgets import QMessageBox
      QMessageBox.information(
          self,
          "Export",
          "Export is not available in this build. Integrate the export dialog to enable.",
      )
  ```

- [x] **Step 7.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowWorkers -v
  ```
  Expected: All 8 tests pass.

- [x] **Step 7.5: Run full suite to check for regressions**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest discover tests/ -v
  ```
  Expected: All tests pass.

- [x] **Step 7.6: Commit**

  ```pwsh
  git add app/ui/main_window.py tests/test_ui_main_window.py
  git commit -m "feat: wire QThread workers into main window with cancel and status bar updates"
  ```

---

## Task 8: Session-Aware Document Open Flow and Identity Dialog

**Files:**
- Create: `app/ui/identity_dialog.py`
- Modify: `app/ui/main_window.py`
- Modify: `tests/test_ui_main_window.py`

### Step 8.1: Write failing tests for document open flow

Add to `tests/test_ui_main_window.py`:

```python
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
        from app.ui.main_window import SpellScribeMainWindow
        win = self._make_window()
        existing_session = MagicMock()
        existing_session.source_sha256_hex = "a" * 64
        existing_session.last_open_path = "/old/path.pdf"
        existing_session.records = []
        win._session = existing_session

        same_path = "/new/same-file.pdf"
        with patch("app.ui.main_window.compute_sha256_hex", return_value="a" * 64), \
             patch("app.ui.main_window.restore_session_state_for_source",
                   return_value=existing_session):
            win._open_document(same_path)

        self.assertIn("same-file.pdf", win.windowTitle())
        self.assertIn(Path(same_path).name, win._status_bar.currentMessage())
        # Session object stays the same (not replaced)
        self.assertIs(win._session, existing_session)

    def test_identity_dialog_abort_leaves_session_unchanged(self):
        win = self._make_window()
        original_session = MagicMock()
        original_session.source_sha256_hex = "a" * 64
        win._session = original_session

        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), \
             patch("app.ui.main_window.restore_session_state_for_source", return_value=None), \
             patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, \
             patch("app.ui.main_window.route_document") as mock_route:
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
        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), \
             patch("app.ui.main_window.restore_session_state_for_source", return_value=None), \
             patch("app.ui.main_window.QMessageBox") as mock_mb:
            mock_box = MagicMock()
            mock_mb.return_value = mock_box
            # Simulate cancel
            mock_box.clickedButton.return_value = MagicMock()  # neither export nor discard
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
        with patch("app.ui.main_window.compute_sha256_hex", return_value="c" * 64), \
             patch("app.ui.main_window.restore_session_state_for_source", return_value=None), \
             patch("app.ui.main_window.QMessageBox") as mock_mb, \
             patch("app.ui.main_window.DocumentIdentityDialog") as mock_dlg_cls, \
             patch("app.ui.main_window.route_document") as mock_route:
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
        with patch("app.ui.main_window.QFileDialog.getOpenFileName",
                   return_value=("", "")) as mock_dlg:
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
        with patch("app.ui.main_window.compute_sha256_hex", return_value="b" * 64), \
             patch("app.ui.main_window.restore_session_state_for_source", return_value=None):
            box = MagicMock()
            export_btn = MagicMock()
            discard_btn = MagicMock()
            cancel_btn = MagicMock()
            with patch("app.ui.main_window.QMessageBox", return_value=box) as mock_mb_cls:
                box.addButton.side_effect = [export_btn, discard_btn, cancel_btn]
                box.clickedButton.return_value = export_btn
                mock_mb_cls.information = MagicMock()
                win._open_document("/new/file.pdf")
            # Session should NOT have changed
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
        with patch("app.ui.main_window.compute_sha256_hex", return_value=new_sha), \
             patch("app.ui.main_window.route_document", return_value=new_routed), \
             patch("app.ui.main_window.restore_session_state_for_source", return_value=None), \
             patch("app.ui.main_window.DocumentIdentityDialog") as mock_id_dlg, \
             patch("app.ui.main_window.QMessageBox") as mock_mb:
            # Identity dialog returns a valid input
            mock_id_dlg.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_id_dlg.return_value.get_identity_input.return_value = MagicMock()
            box = MagicMock()
            mock_mb.return_value = box
            box.exec.return_value = 0
            export_btn = MagicMock()
            cancel_btn = MagicMock()
            box.addButton.side_effect = [export_btn, discard_btn, cancel_btn]
            box.clickedButton.return_value = discard_btn
            win._open_document(new_path)
        # Session was replaced with the new document's session
        self.assertEqual(win._session.source_sha256_hex, new_sha)

    def test_different_sha_export_then_replace_deferred(self):
        """Spec: Export → opens export dialog then replaces session. DEFERRED — Export not in scope."""
        self.skipTest("Export not implemented in this change; see out-of-scope note in Task 8.4")


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
        from app.ui.identity_dialog import DocumentIdentityDialog
        from app.pipeline.identity import DocumentIdentityInput
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
```

- [x] **Step 8.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestDocumentOpenFlow tests.test_ui_main_window.TestIdentityDialog -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.identity_dialog'` and open flow tests fail.

- [x] **Step 8.3: Create `app/ui/identity_dialog.py`**

  ```python
  """Dialog for capturing document identity metadata for unknown SHA-256 hashes."""
  from __future__ import annotations

  from PySide6.QtWidgets import (
      QCheckBox,
      QDialog,
      QDialogButtonBox,
      QFormLayout,
      QLabel,
      QLineEdit,
      QSpinBox,
      QVBoxLayout,
      QWidget,
  )

  from app.pipeline.identity import DocumentIdentityInput


  class DocumentIdentityDialog(QDialog):
      """Shown when the source document's SHA-256 is not yet recorded in config."""

      def __init__(
          self,
          *,
          sha256_hex: str,
          default_document_name: str,
          parent: QWidget | None = None,
      ) -> None:
          super().__init__(parent)
          self.setWindowTitle("New Document — Set Identity")
          self._build_ui(sha256_hex, default_document_name)

      def _build_ui(self, sha256_hex: str, default_document_name: str) -> None:
          layout = QVBoxLayout(self)
          layout.addWidget(QLabel(
              "This document has not been seen before. "
              "Please provide its identity information."
          ))
          layout.addWidget(QLabel(f"SHA-256: {sha256_hex[:16]}…"))

          form = QFormLayout()
          self._name_edit = QLineEdit(default_document_name)
          form.addRow("Document name:", self._name_edit)

          self._offset_spin = QSpinBox()
          self._offset_spin.setRange(0, 9999)
          self._offset_spin.setValue(0)
          form.addRow("Page offset:", self._offset_spin)

          self._force_ocr_check = QCheckBox("Force OCR for this document")
          form.addRow("", self._force_ocr_check)
          layout.addLayout(form)

          buttons = QDialogButtonBox(
              QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
          )
          buttons.accepted.connect(self.accept)
          buttons.rejected.connect(self.reject)
          layout.addWidget(buttons)

      def get_result(self) -> DocumentIdentityInput:
          return DocumentIdentityInput(
              source_display_name=self._name_edit.text().strip(),
              page_offset=self._offset_spin.value(),
              force_ocr=self._force_ocr_check.isChecked(),
          )
  ```

- [x] **Step 8.4: Implement `_open_document` and `_on_open_file` in `app/ui/main_window.py`**

  Add these imports to `app/ui/main_window.py`:
  ```python
  import fitz  # module-level so tests can patch "app.ui.main_window.fitz"

  from pathlib import Path

  from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

  from app.pipeline.identity import DocumentIdentityInput, compute_sha256_hex
  from app.pipeline.ingestion import route_document
  from app.session import restore_session_state_for_source
  from app.ui.identity_dialog import DocumentIdentityDialog
  ```

  Replace stub `_on_open_file`:
  ```python
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
  ```

  Add new `_open_document` method:
  ```python
  def _open_document(self, path: str) -> None:
      """Hash the file, check for existing session, prompt if needed, then route."""
      try:
          sha256 = compute_sha256_hex(path)
      except OSError as exc:
          QMessageBox.critical(self, "Cannot Open File", str(exc))
          return

      # Same-SHA reopen: keep in-memory session AS-IS, just refresh display path
      if (self._session is not None
              and self._session.source_sha256_hex == sha256):
          filename = Path(path).name
          self.setWindowTitle(f"{filename} \u2014 SpellScribe")
          self._config.last_import_directory = str(Path(path).parent)
          self._status_bar.showMessage(f"Reopened: {Path(path).name}")
          return

      # Different-SHA: if confirmed/needs-review records exist, prompt user
      if self._session is not None:
          has_committed = any(
              r.status.value in ("confirmed", "needs_review")
              for r in self._session.records
          )
          if has_committed:
              box = QMessageBox(self)
              box.setWindowTitle("Unsaved Session")
              box.setText("The current session has confirmed or reviewed spells. "
                          "Opening a new document will replace this session.")
              export_btn = box.addButton("Export\u2026", QMessageBox.ButtonRole.ActionRole)
              discard_btn = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
              box.addButton(QMessageBox.StandardButton.Cancel)
              box.setDefaultButton(QMessageBox.StandardButton.Cancel)
              box.exec()
              clicked = box.clickedButton()
              if clicked == export_btn:
                  # Export not integrated in this build — abort to preserve data
                  QMessageBox.information(  # Spec deviation: Export out of scope
                      self,
                      "Export Required First",
                      "Please use the Export toolbar action before opening a new document. "
                      "(Export is not available in this build.)",
                  )
                  return   # Do NOT replace the session
              elif clicked == discard_btn:
                  pass     # Fall through to replace
              else:
                  return   # Cancel — abort open

      # If SHA is not yet recorded, resolve identity before routing
      if sha256 not in getattr(self._config, "document_names_by_sha256", {}):
          dlg = DocumentIdentityDialog(
              sha256_hex=sha256,
              default_document_name=self._config.default_source_document,
              parent=self,
          )
          if dlg.exec() != QDialog.DialogCode.Accepted:
              return  # User cancelled — route_document never called
          identity_result = dlg.get_result()
          self._config.document_names_by_sha256[sha256] = identity_result.source_display_name
          if identity_result.page_offset:
              self._config.document_offsets[sha256] = identity_result.page_offset
          if identity_result.force_ocr:
              self._config.force_ocr_by_sha256[sha256] = True

      try:
          routed = route_document(path, config=self._config)
      except Exception:
          return

      self._routed_document = routed
      from app.session import SessionState
      session = restore_session_state_for_source(sha256)
      if session is None:
          from app.models import CoordinateAwareTextMap
          from app.session import SessionState
          session = SessionState(
              source_sha256_hex=sha256,
              last_open_path=path,
              coordinate_map=routed.coordinate_map,
              records=[],
          )
      self._config.last_import_directory = str(Path(path).parent)
      self._set_session(session, source_path=path)
  ```

  > **Out of scope — "Different-SHA open → Export" (desktop-workbench spec):**
  > When the user has unsaved work and opens a different document, choosing
  > "Export" is supposed to open the export dialog then replace the session.
  > Since Export is not implemented in this change, clicking "Export" shows
  > an information dialog and **aborts the open operation** — the user cannot
  > proceed with either the export or the document switch. This is an active
  > UX regression that must be resolved when the Export feature is implemented.
  > Tracked in `test_different_sha_export_then_replace_deferred` (skipTest).

  > **Note:** `QDialog`, `QFileDialog`, and `QMessageBox` are already imported at module level in Step 8.4's imports block, along with `DocumentIdentityDialog`. No further import changes needed here. `SettingsDialog` is imported in Task 10 when `_on_settings` is wired.

- [x] **Step 8.5: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestDocumentOpenFlow tests.test_ui_main_window.TestIdentityDialog -v
  ```
  Expected: All 8 tests pass.

- [x] **Step 8.6: Run full suite to check for regressions**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest discover tests/ -v
  ```
  Expected: All tests pass.

- [x] **Step 8.7: Commit**

  ```pwsh
  git add app/ui/identity_dialog.py app/ui/main_window.py tests/test_ui_main_window.py
  git commit -m "feat: implement document open flow with same-SHA restore and identity dialog"
  ```

---

## Task 9: Settings Dialog — Base Controls

**Files:**
- Create: `app/ui/settings_dialog.py`
- Create: `tests/test_ui_settings_dialog.py`

### Step 9.1: Write failing tests

Create `tests/test_ui_settings_dialog.py`:

```python
"""Tests for SettingsDialog — persistence, cancel no-op, field loading."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _make_config(**overrides):
    from app.config import AppConfig
    config = AppConfig()
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


class TestSettingsDialogLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_dialog(self, config=None):
        from app.ui.settings_dialog import SettingsDialog
        if config is None:
            config = _make_config()
        return SettingsDialog(config=config)

    def test_stage1_model_field_pre_filled(self):
        config = _make_config(stage1_model="claude-haiku-custom")
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_stage1_model.text(), "claude-haiku-custom")

    def test_stage2_model_field_pre_filled(self):
        config = _make_config(stage2_model="claude-sonnet-custom")
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_stage2_model.text(), "claude-sonnet-custom")

    def test_confidence_threshold_field_pre_filled(self):
        config = _make_config(confidence_threshold=0.75)
        dlg = self._make_dialog(config)
        self.assertAlmostEqual(dlg._field_confidence.value(), 0.75, places=2)

    def test_stage1_empty_page_cutoff_pre_filled(self):
        config = _make_config(stage1_empty_page_cutoff=15)
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_stage1_cutoff.value(), 15)

    def test_max_concurrent_extractions_pre_filled(self):
        config = _make_config(max_concurrent_extractions=3)
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_max_concurrent.value(), 3)

    def test_export_directory_pre_filled(self):
        config = _make_config(export_directory="/my/exports")
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_export_dir.text(), "/my/exports")

    def test_tesseract_path_pre_filled(self):
        config = _make_config(tesseract_path="C:/tesseract/tesseract.exe")
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_tesseract.text(), "C:/tesseract/tesseract.exe")

    def test_default_source_document_pre_filled(self):
        config = _make_config(default_source_document="grimoire.pdf")
        dlg = self._make_dialog(config)
        self.assertEqual(dlg._field_default_source.text(), "grimoire.pdf")


class TestSettingsDialogPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_dialog(self, config=None):
        from app.ui.settings_dialog import SettingsDialog
        if config is None:
            config = _make_config()
        return SettingsDialog(config=config)

    def test_save_writes_config_to_disk(self):
        dlg = self._make_dialog()
        dlg._field_stage1_model.setText("new-haiku")
        with patch.object(dlg._working_config.__class__, "save") as mock_save:
            dlg._on_save()
            mock_save.assert_called_once()

    def test_save_updates_stage1_model(self):
        config = _make_config()
        dlg = self._make_dialog(config)
        dlg._field_stage1_model.setText("changed-model")
        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()
        # The original config object should be updated
        self.assertEqual(config.stage1_model, "changed-model")

    def test_cancel_does_not_write_to_disk(self):
        dlg = self._make_dialog()
        dlg._field_stage2_model.setText("should-not-persist")
        with patch.object(dlg._working_config.__class__, "save") as mock_save:
            dlg._on_cancel()
            mock_save.assert_not_called()

    def test_cancel_does_not_change_original_config(self):
        config = _make_config(stage2_model="original-model")
        dlg = self._make_dialog(config)
        dlg._field_stage2_model.setText("modified-model")
        dlg._on_cancel()
        self.assertEqual(config.stage2_model, "original-model")
```

- [x] **Step 9.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_settings_dialog -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.ui.settings_dialog'`

- [x] **Step 9.3: Create `app/ui/settings_dialog.py`**

  ```python
  """Settings dialog: edit AppConfig fields with Save/Cancel semantics."""
  from __future__ import annotations

  import copy
  from pathlib import Path
  from typing import TYPE_CHECKING

  from PySide6.QtWidgets import (
      QApplication,
      QDialog,
      QDialogButtonBox,
      QDoubleSpinBox,
      QFileDialog,
      QFormLayout,
      QHBoxLayout,
      QLabel,
      QLineEdit,
      QPushButton,
      QScrollArea,
      QSpinBox,
      QVBoxLayout,
      QWidget,
  )

  if TYPE_CHECKING:
      from app.config import AppConfig


  class SettingsDialog(QDialog):
      """Edit AppConfig; writes to disk only on Save.

      Fields NOT surfaced per spec: stage2_max_attempts, last_import_directory,
      last_export_scope, custom_schools, custom_spheres, document_names_by_sha256,
      document_offsets, force_ocr_by_sha256.
      """

      def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._original_config = config
          self._working_config = copy.deepcopy(config)
          self.setWindowTitle("Settings")
          self._build_ui()

      # ------------------------------------------------------------------
      # UI Construction
      # ------------------------------------------------------------------

      def _build_ui(self) -> None:
          outer = QVBoxLayout(self)

          scroll = QScrollArea()
          scroll.setWidgetResizable(True)
          form_widget = QWidget()
          form = QFormLayout(form_widget)
          scroll.setWidget(form_widget)
          outer.addWidget(scroll)

          # LLM models
          self._field_stage1_model = QLineEdit(self._working_config.stage1_model)
          form.addRow("Stage 1 model:", self._field_stage1_model)

          self._field_stage2_model = QLineEdit(self._working_config.stage2_model)
          form.addRow("Stage 2 model:", self._field_stage2_model)

          # Extraction parameters
          self._field_stage1_cutoff = QSpinBox()
          self._field_stage1_cutoff.setRange(0, 10000)
          self._field_stage1_cutoff.setValue(self._working_config.stage1_empty_page_cutoff)
          form.addRow("Stage 1 empty-page cutoff:", self._field_stage1_cutoff)

          self._field_max_concurrent = QSpinBox()
          self._field_max_concurrent.setRange(1, 20)
          self._field_max_concurrent.setValue(self._working_config.max_concurrent_extractions)
          form.addRow("Max concurrent extractions:", self._field_max_concurrent)

          self._field_confidence = QDoubleSpinBox()
          self._field_confidence.setRange(0.0, 1.0)
          self._field_confidence.setSingleStep(0.05)
          self._field_confidence.setDecimals(2)
          self._field_confidence.setValue(self._working_config.confidence_threshold)
          form.addRow("Confidence threshold:", self._field_confidence)

          # Paths
          self._field_tesseract = QLineEdit(self._working_config.tesseract_path)
          tesseract_row = self._path_row(self._field_tesseract, is_file=True)
          form.addRow("Tesseract path:", tesseract_row)

          self._field_export_dir = QLineEdit(self._working_config.export_directory)
          export_row = self._path_row(self._field_export_dir, is_file=False)
          form.addRow("Export directory:", export_row)

          self._field_default_source = QLineEdit(self._working_config.default_source_document)
          form.addRow("Default source document:", self._field_default_source)

          # Save / Cancel buttons — created BEFORE credential controls so _save_button is available
          buttons = QDialogButtonBox(
              QDialogButtonBox.StandardButton.Save
              | QDialogButtonBox.StandardButton.Cancel
          )
          self._save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
          buttons.accepted.connect(self._on_save)
          buttons.rejected.connect(self._on_cancel)

          # Credential controls (Task 10 adds radio group here)
          self._build_credential_controls(form)

          outer.addWidget(buttons)

      def _path_row(self, line_edit: QLineEdit, *, is_file: bool) -> QWidget:
          row = QWidget()
          h = QHBoxLayout(row)
          h.setContentsMargins(0, 0, 0, 0)
          h.addWidget(line_edit)
          browse_btn = QPushButton("Browse…")
          if is_file:
              browse_btn.clicked.connect(
                  lambda: self._browse_file(line_edit)
              )
          else:
              browse_btn.clicked.connect(
                  lambda: self._browse_directory(line_edit)
              )
          h.addWidget(browse_btn)
          return row

      def _browse_file(self, line_edit: QLineEdit) -> None:
          path, _ = QFileDialog.getOpenFileName(self, "Select file", line_edit.text())
          if path:
              line_edit.setText(path)

      def _browse_directory(self, line_edit: QLineEdit) -> None:
          path = QFileDialog.getExistingDirectory(self, "Select directory", line_edit.text())
          if path:
              line_edit.setText(path)

      def _build_credential_controls(self, form: QFormLayout) -> None:
          # Placeholder; full radio group added in Task 10
          form.addRow(QLabel("API key source: (configure in Task 10)"))

      # ------------------------------------------------------------------
      # Save / Cancel
      # ------------------------------------------------------------------

      def _apply_fields_to_working_config(self) -> None:
          self._working_config.stage1_model = self._field_stage1_model.text().strip()
          self._working_config.stage2_model = self._field_stage2_model.text().strip()
          self._working_config.stage1_empty_page_cutoff = self._field_stage1_cutoff.value()
          self._working_config.max_concurrent_extractions = self._field_max_concurrent.value()
          self._working_config.confidence_threshold = self._field_confidence.value()
          self._working_config.tesseract_path = self._field_tesseract.text().strip()
          self._working_config.export_directory = self._field_export_dir.text().strip()
          self._working_config.default_source_document = self._field_default_source.text().strip()

      def _on_save(self) -> None:
          self._apply_fields_to_working_config()
          self._working_config.save()
          # Update original config in-place so the running app picks up changes
          for field_name in vars(self._working_config):
              setattr(self._original_config, field_name, getattr(self._working_config, field_name))
          self.accept()

      def _on_cancel(self) -> None:
          self.reject()
  ```

- [x] **Step 9.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_settings_dialog -v
  ```
  Expected: All 12 tests pass.

- [x] **Step 9.5: Commit**

  ```pwsh
  git add app/ui/settings_dialog.py tests/test_ui_settings_dialog.py
  git commit -m "feat: add SettingsDialog with field loading, Save/Cancel semantics"
  ```

---

## Task 10: Credential Controls and Test API Key

**Files:**
- Modify: `app/ui/settings_dialog.py`
- Modify: `tests/test_ui_settings_dialog.py`

### Step 10.1: Write failing tests for credential controls

Add to `tests/test_ui_settings_dialog.py`:

```python
class TestCredentialControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_dialog(self, mode="env"):
        from app.ui.settings_dialog import SettingsDialog
        config = _make_config(api_key_storage_mode=mode)
        return SettingsDialog(config=config)

    def test_env_mode_hides_key_field_shows_note(self):
        dlg = self._make_dialog(mode="env")
        self.assertFalse(dlg._key_field.isVisible())
        self.assertTrue(dlg._env_note_label.isVisible())

    def test_credential_manager_mode_hides_key_field(self):
        dlg = self._make_dialog(mode="credential_manager")
        self.assertFalse(dlg._key_field.isVisible())

    def test_local_plaintext_mode_shows_key_field_and_warning(self):
        dlg = self._make_dialog(mode="local_plaintext")
        self.assertTrue(dlg._key_field.isVisible())
        self.assertTrue(dlg._plaintext_warning.isVisible())

    def test_local_plaintext_mode_shows_confirmation_checkbox(self):
        dlg = self._make_dialog(mode="local_plaintext")
        self.assertTrue(dlg._plaintext_confirm_check.isVisible())

    def test_save_blocked_in_plaintext_mode_until_confirmed(self):
        dlg = self._make_dialog(mode="local_plaintext")
        # Confirmation checkbox unchecked by default
        dlg._plaintext_confirm_check.setChecked(False)
        self.assertFalse(dlg._save_button.isEnabled())

    def test_save_enabled_in_plaintext_mode_when_confirmed(self):
        dlg = self._make_dialog(mode="local_plaintext")
        dlg._plaintext_confirm_check.setChecked(True)
        self.assertTrue(dlg._save_button.isEnabled())

    def test_show_hide_toggle_reveals_key_field_text(self):
        from PySide6.QtWidgets import QLineEdit
        dlg = self._make_dialog(mode="local_plaintext")
        # Default: masked
        self.assertEqual(
            dlg._key_field.echoMode(), QLineEdit.EchoMode.Password
        )
        dlg._toggle_key_visibility()
        self.assertEqual(
            dlg._key_field.echoMode(), QLineEdit.EchoMode.Normal
        )

    def test_test_api_key_disabled_in_env_mode_when_var_not_set(self):
        dlg = self._make_dialog(mode="env")
        with patch.dict("os.environ", {}, clear=True):
            # Simulate no ANTHROPIC_API_KEY
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            dlg._update_test_key_button_state()
        self.assertFalse(dlg._btn_test_key.isEnabled())

    def test_test_api_key_disabled_in_plaintext_mode_when_field_empty(self):
        dlg = self._make_dialog(mode="local_plaintext")
        dlg._key_field.setText("")
        dlg._update_test_key_button_state()
        self.assertFalse(dlg._btn_test_key.isEnabled())

    def test_test_api_key_enabled_in_plaintext_mode_when_field_has_value(self):
        dlg = self._make_dialog(mode="local_plaintext")
        dlg._key_field.setText("sk-ant-test123")
        dlg._update_test_key_button_state()
        self.assertTrue(dlg._btn_test_key.isEnabled())


class TestSettingsDialogTestKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_dialog(self, config):
        from app.ui.settings_dialog import SettingsDialog
        return SettingsDialog(config=config)

    def test_test_api_key_success_shows_success_label(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = MagicMock()
            dlg._on_test_api_key()
        self.assertIn("success", dlg._test_key_result.text().lower())

    def test_test_api_key_failure_shows_error_label(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.models.list.side_effect = Exception("invalid_api_key")
            dlg._on_test_api_key()
        self.assertIn("invalid_api_key", dlg._test_key_result.text())
```

- [x] **Step 10.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_settings_dialog.TestCredentialControls -v
  ```
  Expected: Tests fail because credential controls don't exist yet.

- [x] **Step 10.3: Add credential controls to `app/ui/settings_dialog.py`**

  Add these imports to `settings_dialog.py`:
  ```python
  import os

  from app.config import CREDENTIAL_ACCOUNT_NAME, CREDENTIAL_SERVICE_NAME
  from PySide6.QtWidgets import (
      QButtonGroup,
      QCheckBox,
      QRadioButton,
  )
  ```

  Replace `_build_credential_controls` and extend `__init__`:
  ```python
  def _build_credential_controls(self, form: QFormLayout) -> None:
      from PySide6.QtWidgets import QGroupBox

      group = QGroupBox("API Key Source")
      g_layout = QVBoxLayout(group)

      self._rb_env = QRadioButton("Environment variable (ANTHROPIC_API_KEY)")
      self._rb_credential_manager = QRadioButton("Windows Credential Manager")
      self._rb_local_plaintext = QRadioButton("Store in config.json (plaintext)")

      self._radio_group = QButtonGroup(self)
      self._radio_group.addButton(self._rb_env, 0)
      self._radio_group.addButton(self._rb_credential_manager, 1)
      self._radio_group.addButton(self._rb_local_plaintext, 2)

      g_layout.addWidget(self._rb_env)
      g_layout.addWidget(self._rb_credential_manager)
      g_layout.addWidget(self._rb_local_plaintext)

      # Env note
      self._env_note_label = QLabel("Set the ANTHROPIC_API_KEY environment variable.")
      self._env_note_label.setStyleSheet("color: grey; font-style: italic;")
      g_layout.addWidget(self._env_note_label)

      # Plaintext key field
      key_row = QWidget()
      key_layout = QHBoxLayout(key_row)
      key_layout.setContentsMargins(0, 0, 0, 0)
      self._key_field = QLineEdit()
      self._key_field.setEchoMode(QLineEdit.EchoMode.Password)
      self._key_field.setPlaceholderText("API key")
      self._key_field.textChanged.connect(self._update_test_key_button_state)
      self._key_toggle_btn = QPushButton("Show")
      self._key_toggle_btn.setCheckable(True)
      self._key_toggle_btn.clicked.connect(self._toggle_key_visibility)
      key_layout.addWidget(self._key_field)
      key_layout.addWidget(self._key_toggle_btn)
      g_layout.addWidget(key_row)

      # Plaintext risk warning
      self._plaintext_warning = QLabel(
          "⚠ Key will be stored unencrypted in config.json "
          "without OS keyring protection."
      )
      self._plaintext_warning.setStyleSheet("color: #c0392b; font-weight: bold;")
      self._plaintext_warning.setWordWrap(True)
      g_layout.addWidget(self._plaintext_warning)

      # Confirmation checkbox
      self._plaintext_confirm_check = QCheckBox(
          "I understand and accept the risk of plaintext key storage."
      )
      self._plaintext_confirm_check.stateChanged.connect(self._update_save_button_state)
      g_layout.addWidget(self._plaintext_confirm_check)

      # Test API Key button
      self._btn_test_key = QPushButton("Test API Key")
      self._btn_test_key.clicked.connect(self._on_test_api_key)
      self._test_key_result = QLabel("")
      g_layout.addWidget(self._btn_test_key)
      g_layout.addWidget(self._test_key_result)

      form.addRow(group)

      # Set initial mode
      mode = self._working_config.api_key_storage_mode
      if mode == "credential_manager":
          self._rb_credential_manager.setChecked(True)
      elif mode == "local_plaintext":
          self._rb_local_plaintext.setChecked(True)
          if self._working_config.api_key:
              self._key_field.setText(self._working_config.api_key)
      else:
          self._rb_env.setChecked(True)

      self._radio_group.buttonClicked.connect(self._on_credential_mode_changed)
      self._on_credential_mode_changed(None)

  def _on_credential_mode_changed(self, _button) -> None:
      is_env = self._rb_env.isChecked()
      is_plaintext = self._rb_local_plaintext.isChecked()

      self._env_note_label.setVisible(is_env)
      self._key_field.setVisible(is_plaintext)
      self._key_toggle_btn.setVisible(is_plaintext)
      self._plaintext_warning.setVisible(is_plaintext)
      self._plaintext_confirm_check.setVisible(is_plaintext)
      if not is_plaintext:
          self._plaintext_confirm_check.setChecked(False)

      self._update_test_key_button_state()
      self._update_save_button_state()

  def _toggle_key_visibility(self) -> None:
      from PySide6.QtWidgets import QLineEdit
      if self._key_field.echoMode() == QLineEdit.EchoMode.Password:
          self._key_field.setEchoMode(QLineEdit.EchoMode.Normal)
          self._key_toggle_btn.setText("Hide")
      else:
          self._key_field.setEchoMode(QLineEdit.EchoMode.Password)
          self._key_toggle_btn.setText("Show")

  def _update_test_key_button_state(self) -> None:
      if self._rb_env.isChecked():
          enabled = bool(os.environ.get("ANTHROPIC_API_KEY"))
      elif self._rb_local_plaintext.isChecked():
          enabled = bool(self._key_field.text().strip())
      else:
          # credential_manager: always enabled (key is retrieved at runtime)
          enabled = True
      self._btn_test_key.setEnabled(enabled)

  def _update_save_button_state(self) -> None:
      if self._rb_local_plaintext.isChecked():
          can_save = self._plaintext_confirm_check.isChecked()
      else:
          can_save = True
      if hasattr(self, "_save_button") and self._save_button:
          self._save_button.setEnabled(can_save)

  def _on_test_api_key(self) -> None:
      """Resolve key from current (unsaved) selection; make a lightweight API ping."""
      import anthropic

      if self._rb_env.isChecked():
          api_key = os.environ.get("ANTHROPIC_API_KEY", "")
      elif self._rb_local_plaintext.isChecked():
          api_key = self._key_field.text().strip()
      else:
          import keyring
          api_key = keyring.get_password(CREDENTIAL_SERVICE_NAME, CREDENTIAL_ACCOUNT_NAME) or ""

      if not api_key:
          self._test_key_result.setText("No API key to test.")
          return

      self._btn_test_key.setEnabled(False)
      self._test_key_result.setText("Testing…")
      QApplication.processEvents()

      try:
          client = anthropic.Anthropic(api_key=api_key)
          client.models.list()
          self._test_key_result.setText("✓ API key is valid.")
          self._test_key_result.setStyleSheet("color: green;")
      except Exception as exc:
          self._test_key_result.setText(f"✗ {exc}")
          self._test_key_result.setStyleSheet("color: red;")
      finally:
          self._update_test_key_button_state()
  ```

  Also update `_apply_fields_to_working_config` to include credential fields:
  ```python
  def _apply_fields_to_working_config(self) -> None:
      self._working_config.stage1_model = self._field_stage1_model.text().strip()
      self._working_config.stage2_model = self._field_stage2_model.text().strip()
      self._working_config.stage1_empty_page_cutoff = self._field_stage1_cutoff.value()
      self._working_config.max_concurrent_extractions = self._field_max_concurrent.value()
      self._working_config.confidence_threshold = self._field_confidence.value()
      self._working_config.tesseract_path = self._field_tesseract.text().strip()
      self._working_config.export_directory = self._field_export_dir.text().strip()
      self._working_config.default_source_document = self._field_default_source.text().strip()
      if self._rb_env.isChecked():
          self._working_config.api_key_storage_mode = "env"
          self._working_config.api_key = ""
      elif self._rb_credential_manager.isChecked():
          self._working_config.api_key_storage_mode = "credential_manager"
          self._working_config.api_key = ""
      else:
          self._working_config.api_key_storage_mode = "local_plaintext"
          self._working_config.api_key = self._key_field.text().strip()
  ```

  Add `from PySide6.QtWidgets import QApplication` to the import block.

- [x] **Step 10.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_settings_dialog -v
  ```
  Expected: All 22 tests pass.

- [x] **Step 10.5: Write and run settings action test (confirm failure)**

  Add to `tests/test_ui_main_window.py` in `TestMainWindowToolbar`:

  ```python
  def test_settings_action_opens_settings_dialog(self):
      win = self._make_window()
      with patch("app.ui.main_window.SettingsDialog") as mock_dlg_cls:
          mock_dlg = MagicMock()
          mock_dlg_cls.return_value = mock_dlg
          win._on_settings()
          mock_dlg_cls.assert_called_once()
          mock_dlg.exec.assert_called_once()
  ```

  Run:
  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowToolbar.test_settings_action_opens_settings_dialog -v
  ```
  Expected: Test fails — `_on_settings` is a stub.

- [x] **Step 10.6: Wire settings action in main window and confirm all tests pass**

  Add to `app/ui/main_window.py` module-level imports:
  ```python
  from app.ui.settings_dialog import SettingsDialog
  ```
  This must be at module level so the patch target `"app.ui.main_window.SettingsDialog"` resolves in tests.

  In `app/ui/main_window.py`, replace stub `_on_settings`:
  ```python
  def _on_settings(self) -> None:
      dlg = SettingsDialog(config=self._config, parent=self)
      dlg.exec()
  ```

  Run:
  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowToolbar.test_settings_action_opens_settings_dialog -v
  ```
  Expected: All tests pass.

- [x] **Step 10.7: Run full test suite**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest discover tests/ -v
  ```
  Expected: All tests pass.

- [x] **Step 10.8: Commit**

  ```pwsh
  git add app/ui/settings_dialog.py app/ui/main_window.py tests/test_ui_settings_dialog.py
  git commit -m "feat: add credential-source radio group, Test API Key button, and plaintext confirmation gate"
  ```

---

## Task 11: Wire Main Window Panels Together

**Files:**
- Modify: `app/ui/main_window.py`
- Modify: `tests/test_ui_main_window.py`

This task connects `SpellListPanel` selection → `ReviewPanel` + `DocumentPanel` refresh. Until now these were stub placeholders.

### Step 11.1: Write failing integration test

Add to `tests/test_ui_main_window.py`:

```python
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
        return SpellScribeMainWindow(config=config)

    def test_panels_created_after_construction(self):
        win = self._make_window_with_panels()
        from app.ui.document_panel import DocumentPanel
        from app.ui.spell_list_panel import SpellListPanel
        from app.ui.review_panel import ReviewPanel
        # All three panels should be present in the widget tree
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
        win._session = session
        with patch.object(win._review_panel, "show_pending_record") as mock_pending:
            win._on_spell_selected("p1")
            mock_pending.assert_called_once_with(pending_record)

    def test_spell_selection_routes_confirmed_to_review_panel(self):
        win = self._make_window_with_panels()
        confirmed_record = MagicMock()
        confirmed_record.status.value = "confirmed"
        win._session = MagicMock()
        win._session.records = [confirmed_record]
        win._session.selected_spell_id = confirmed_record.spell_id
        with patch.object(win._review_panel, "show_review_record") as mock_show:
            win._on_spell_selected(confirmed_record.spell_id)
            mock_show.assert_called_once_with(confirmed_record, win._session)

    def test_document_panel_shows_placeholder_at_startup(self):
        win = self._make_window_with_panels()
        from app.ui.document_panel import DocumentPanel
        doc_panel = win.findChild(DocumentPanel)
        self.assertTrue(doc_panel._placeholder_label.isVisible())

    def test_spell_list_panel_starts_with_empty_sections(self):
        win = self._make_window_with_panels()
        from app.ui.spell_list_panel import SpellListPanel
        spell_panel = win.findChild(SpellListPanel)
        total = (spell_panel._confirmed_list.count()
                 + spell_panel._needs_review_list.count()
                 + spell_panel._pending_list.count())
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
        pending_record.status.value = "pending_extraction"
        session = MagicMock()
        session.records = [pending_record]
        captured_copy_args = {}
        def fake_model_copy(**kwargs):
            captured_copy_args.update(kwargs)
            return session  # return same mock
        session.model_copy.side_effect = fake_model_copy
        win._session = session
        with patch.object(win._review_panel, "show_pending_record"):
            win._on_spell_selected("spell-42")
        self.assertIn("selected_spell_id", captured_copy_args.get("update", {}))
        self.assertEqual(captured_copy_args["update"]["selected_spell_id"], "spell-42")

    def test_spell_selection_dispatches_pdf_to_doc_panel(self):
        win = self._make_window_with_panels()
        pending_record = MagicMock()
        pending_record.spell_id = "spell-55"
        pending_record.status.value = "pending_extraction"
        pending_record.boundary_start_line = 0
        pending_record.boundary_end_line = 5
        region = MagicMock()
        region.page = 1  # PDF region (not -1)
        region.bbox = (0.0, 0.0, 100.0, 50.0)
        session = MagicMock()
        session.records = [pending_record]
        session.coordinate_map.regions_for_range.return_value = [region]
        session.last_open_path = "test.pdf"
        session.selected_spell_id = None
        session.model_copy.return_value = session
        win._session = session
        win._routed_document = MagicMock()  # required by _on_spell_selected gate check
        with patch("app.ui.main_window.fitz") as mock_fitz, \
             patch.object(win._doc_panel, "display_pdf_page") as mock_display:
            mock_fitz.open.return_value.__enter__ = MagicMock(return_value=mock_fitz.open.return_value)
            mock_fitz.open.return_value.__exit__ = MagicMock(return_value=False)
            win._on_spell_selected("spell-55")
        mock_display.assert_called_once()
```

- [x] **Step 11.2: Run to confirm failure**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowPanelWiring -v
  ```
  Expected: Test fails because `_build_central_widget` still uses placeholder labels.

- [x] **Step 11.3: Replace placeholder panels with real widgets in `app/ui/main_window.py`**

  Update `_build_central_widget` to use the real panel classes:
  ```python
  def _build_central_widget(self) -> None:
      from app.ui.document_panel import DocumentPanel
      from app.ui.review_panel import ReviewPanel
      from app.ui.spell_list_panel import SpellListPanel

      splitter = QSplitter(Qt.Orientation.Horizontal, self)

      self._doc_panel = DocumentPanel(self)
      splitter.addWidget(self._doc_panel)

      self._spell_list_panel = SpellListPanel(self)
      self._spell_list_panel.selected_spell_id_changed.connect(
          self._on_spell_selected
      )
      splitter.addWidget(self._spell_list_panel)

      self._review_panel = ReviewPanel(config=self._config, parent=self)
      self._review_panel.session_changed.connect(
          lambda s: self._spell_list_panel.refresh(s)
      )
      splitter.addWidget(self._review_panel)

      splitter.setSizes([400, 200, 350])
      self.setCentralWidget(splitter)
  ```

  Add `_on_spell_selected` method:
  ```python
  def _on_spell_selected(self, spell_id: str) -> None:
      if self._session is None:
          return
      record = next(
          (r for r in self._session.records if r.spell_id == spell_id), None
      )
      if record is None:
          return
      self._session = self._session.model_copy(update={"selected_spell_id": spell_id})
      if record.status.value == "pending_extraction":
          self._review_panel.show_pending_record(record)
      else:
          self._review_panel.show_review_record(record, self._session)
      # Update document panel highlight
      if record.boundary_end_line < 0:
          self._doc_panel.show_placeholder()
          return
      regions = self._session.coordinate_map.regions_for_range(
          record.boundary_start_line, record.boundary_end_line
      )
      if regions and self._routed_document is not None:
          first = regions[0]
          if first.page >= 0:
              doc = fitz.open(self._session.last_open_path)
              try:
                  self._doc_panel.display_pdf_page(doc, first.page, regions)
              finally:
                  doc.close()
          else:
              char_ranges = [
                  (r.char_offset[0], r.char_offset[1])
                  for r in regions
                  if r.char_offset is not None
              ]
              self._doc_panel.display_docx(
                  self._routed_document.markdown_text, char_ranges
              )
  ```

  Also update `_set_session` to refresh the spell list:
  ```python
  def _set_session(self, session: SessionState, *, source_path: str) -> None:
      self._session = session
      filename = Path(source_path).name
      self.setWindowTitle(f"{filename} \u2014 SpellScribe")
      self._update_action_states()
      self._spell_list_panel.refresh(session)
  ```

- [x] **Step 11.4: Run tests to confirm they pass**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest tests.test_ui_main_window.TestMainWindowPanelWiring -v
  ```
  Expected: All 6 tests pass.

- [x] **Step 11.5: Run full test suite**

  ```pwsh
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m unittest discover tests/ -v
  ```
  Expected: All tests pass.

- [x] **Step 11.6: Commit**

  ```pwsh
  git add app/ui/main_window.py tests/test_ui_main_window.py
  git commit -m "feat: wire document panel, spell list, and review panel together in main window"
  ```

---

## Final Verification

- [x] **Run the complete test suite one last time**

  ```pwsh
$env:QT_QPA_PLATFORM = "offscreen"
$test_output = python -m unittest discover tests/ -v 2>&1
$test_exit_code = $LASTEXITCODE
$test_output | Select-String -Pattern "OK|FAIL|ERROR"
if ($test_exit_code -ne 0) { exit $test_exit_code }
  ```
  Expected: `OK` — zero failures, zero errors.
    Evidence (2026-04-28): Output marker `OK (skipped=2)`; command exit code `0`.

- [x] **Smoke-test the app launches without errors**

  Create a minimal `__main__` block at the bottom of `app/ui/main_window.py` (for dev use only):
  ```python
  if __name__ == "__main__":
      import sys
      from PySide6.QtWidgets import QApplication
      from app.config import AppConfig
      app = QApplication(sys.argv)
      config = AppConfig.load()
      win = SpellScribeMainWindow(config=config)
      win.resize(1200, 800)
      win.show()
      sys.exit(app.exec())
  ```

  Run it:
  ```pwsh
  python -m app.ui.main_window
  ```
  Expected: Window appears with "SpellScribe" title and disabled toolbar actions (no document loaded).
    Evidence (2026-04-28): Process stayed running for 5 seconds without crashing, then was terminated to complete the smoke check.

- [ ] **Final commit**

  ```pwsh
  git add app/ui/main_window.py
  git commit -m "feat: add dev __main__ launcher for SpellScribeMainWindow"
  ```
