"""Document viewer panel: PDF rendering and DOCX text display."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTextCharFormat, QTextCursor
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


_HIGHLIGHT_COLOR = QColor(255, 220, 50, 120)
_PDF_RENDER_SCALE = 1.5


class DocumentPanel(QWidget):
    """Left panel: displays the current source document with region highlights."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.show()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack)

        self._placeholder_label = QLabel("Open a document to begin.")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._placeholder_label)

        self._pdf_scroll = QScrollArea()
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_page_label = QLabel()
        self._pdf_page_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._pdf_page_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._pdf_scroll.setWidget(self._pdf_page_label)
        self._stack.addWidget(self._pdf_scroll)

        self._docx_edit = QTextEdit()
        self._docx_edit.setReadOnly(True)
        self._stack.addWidget(self._docx_edit)

        self._stack.setCurrentWidget(self._placeholder_label)

    def show_placeholder(self) -> None:
        self._stack.setCurrentWidget(self._placeholder_label)

    def display_pdf_page(
        self,
        fitz_doc: object,
        page_num: int,
        highlight_regions: list[TextRegion],
    ) -> None:
        import fitz  # type: ignore

        page: fitz.Page = fitz_doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(_PDF_RENDER_SCALE, _PDF_RENDER_SCALE))

        if getattr(pix, "n", 3) == 4:
            image_format = QImage.Format.Format_RGBA8888
        else:
            image_format = QImage.Format.Format_RGB888

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, image_format)
        pixmap = QPixmap.fromImage(image)

        if highlight_regions:
            painter = QPainter(pixmap)
            painter.setBrush(_HIGHLIGHT_COLOR)
            painter.setPen(Qt.PenStyle.NoPen)
            for region in highlight_regions:
                bbox = getattr(region, "bbox", None)
                if bbox is None:
                    continue
                x0, y0, x1, y1 = bbox
                painter.drawRect(
                    int(x0 * _PDF_RENDER_SCALE),
                    int(y0 * _PDF_RENDER_SCALE),
                    max(1, int((x1 - x0) * _PDF_RENDER_SCALE)),
                    max(1, int((y1 - y0) * _PDF_RENDER_SCALE)),
                )
            painter.end()

        self._pdf_page_label.setPixmap(pixmap)
        self._stack.setCurrentWidget(self._pdf_scroll)

        if highlight_regions:
            first = highlight_regions[0]
            bbox = getattr(first, "bbox", None)
            if bbox is not None:
                scroll_y = int(bbox[1] * _PDF_RENDER_SCALE)
                self._pdf_scroll.verticalScrollBar().setValue(max(0, scroll_y - 60))

    def display_docx(
        self,
        markdown_text: str,
        highlight_ranges: list[tuple[int, int]],
    ) -> None:
        self._docx_edit.setPlainText(markdown_text)
        selections: list[QTextEdit.ExtraSelection] = []
        if highlight_ranges:
            fmt = QTextCharFormat()
            fmt.setBackground(_HIGHLIGHT_COLOR)
            text_len = len(markdown_text)
            for start, end in highlight_ranges:
                clamped_start = max(0, min(start, text_len))
                clamped_end = max(clamped_start, min(end, text_len))
                cursor = self._docx_edit.textCursor()
                cursor.setPosition(clamped_start)
                cursor.setPosition(clamped_end, QTextCursor.MoveMode.KeepAnchor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)

            first_cursor = self._docx_edit.textCursor()
            first_cursor.setPosition(max(0, min(highlight_ranges[0][0], text_len)))
            self._docx_edit.setTextCursor(first_cursor)
            self._docx_edit.ensureCursorVisible()

        self._docx_edit.setExtraSelections(selections)
        self._stack.setCurrentWidget(self._docx_edit)
