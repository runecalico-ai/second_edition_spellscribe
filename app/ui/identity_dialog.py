"""Dialog for capturing identity metadata for an unknown document hash."""
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
    """Prompted when a document SHA-256 has no configured identity metadata."""

    def __init__(
        self,
        *,
        sha256_hex: str,
        default_document_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Document - Set Identity")
        self._build_ui(sha256_hex=sha256_hex, default_document_name=default_document_name)

    def _build_ui(self, *, sha256_hex: str, default_document_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "This document has not been seen before. "
                "Please provide its identity information."
            )
        )
        layout.addWidget(QLabel(f"SHA-256: {sha256_hex[:16]}..."))

        form = QFormLayout()
        self._name_edit = QLineEdit(default_document_name, self)
        form.addRow("Document name:", self._name_edit)

        self._offset_spin = QSpinBox(self)
        self._offset_spin.setRange(-9999, 9999)
        self._offset_spin.setValue(0)
        form.addRow("Page offset:", self._offset_spin)

        self._force_ocr_check = QCheckBox("Force OCR for this document", self)
        form.addRow("", self._force_ocr_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
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
