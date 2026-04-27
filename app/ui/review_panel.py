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
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.pipeline.extraction import (
    DuplicateResolutionStrategy,
    InvalidRecordStateError,
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
    """Right-side panel that shows pending info or editable review form."""

    session_changed = Signal(object)

    def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._current_record: SpellRecord | None = None
        self._current_session: SessionState | None = None
        self._loading = False
        self._has_validation_errors = False
        self._build_ui()
        self.show()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack)

        self._placeholder_label = QLabel("Select a spell to review.")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._placeholder_label)

        self._pending_widget = self._build_pending_widget()
        self._stack.addWidget(self._pending_widget)

        self._review_widget = self._build_review_widget()
        self._stack.addWidget(self._review_widget)

        self._stack.setCurrentWidget(self._placeholder_label)

    def _build_pending_widget(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("<b>Pending Extraction</b>"))
        self._pending_name_label = QLabel("")
        self._pending_order_label = QLabel("")
        self._pending_range_label = QLabel("")
        layout.addWidget(self._pending_name_label)
        layout.addWidget(self._pending_order_label)
        layout.addWidget(self._pending_range_label)
        layout.addStretch()
        return widget

    def _build_review_widget(self) -> QWidget:
        container = QWidget(self)
        outer = QVBoxLayout(container)

        self._dirty_banner = QLabel("Unsaved changes")
        self._dirty_banner.setStyleSheet("background: #ffe082; padding: 4px;")
        self._dirty_banner.setVisible(False)
        outer.addWidget(self._dirty_banner)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        form_widget = QWidget(scroll)
        self._form_layout = QFormLayout(form_widget)
        scroll.setWidget(form_widget)
        outer.addWidget(scroll)

        self._field_name = QLineEdit(self)
        self._field_level = QLineEdit(self)
        self._field_description = QTextEdit(self)
        self._field_class_list = QComboBox(self)
        self._field_class_list.addItems(["Wizard", "Priest"])
        self._field_school = QLineEdit(self)
        self._field_sphere = QLineEdit(self)
        self._field_range = QLineEdit(self)
        self._field_casting_time = QLineEdit(self)
        self._field_duration = QLineEdit(self)
        self._field_area_of_effect = QLineEdit(self)
        self._field_saving_throw = QLineEdit(self)
        self._field_components = QLineEdit(self)
        self._field_reversible = QCheckBox(self)
        self._field_needs_review = QCheckBox(self)
        self._field_review_notes = QTextEdit(self)
        self._field_review_notes.setMaximumHeight(80)

        self._form_layout.addRow("Name:", self._field_name)
        self._form_layout.addRow("Level:", self._field_level)
        self._form_layout.addRow("Description:", self._field_description)
        self._form_layout.addRow("Class:", self._field_class_list)
        self._form_layout.addRow("School(s):", self._field_school)
        self._form_layout.addRow("Sphere(s):", self._field_sphere)
        self._form_layout.addRow("Range:", self._field_range)
        self._form_layout.addRow("Casting Time:", self._field_casting_time)
        self._form_layout.addRow("Duration:", self._field_duration)
        self._form_layout.addRow("Area of Effect:", self._field_area_of_effect)
        self._form_layout.addRow("Saving Throw:", self._field_saving_throw)
        self._form_layout.addRow("Components:", self._field_components)
        self._form_layout.addRow("Reversible:", self._field_reversible)
        self._form_layout.addRow("Needs Review:", self._field_needs_review)
        self._form_layout.addRow("Review Notes:", self._field_review_notes)

        self._field_name.editingFinished.connect(self._on_field_edited)
        self._field_level.editingFinished.connect(self._on_field_edited)
        self._field_description.textChanged.connect(self._on_field_edited)
        self._field_class_list.currentTextChanged.connect(self._on_field_edited)
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

        self._btn_save = QPushButton("Save Confirmed", self)
        self._btn_accept = QPushButton("Accept (Needs Review)", self)
        self._btn_reextract = QPushButton("Re-extract...", self)
        self._btn_discard = QPushButton("Discard Draft", self)
        self._btn_delete = QPushButton("Delete", self)

        self._btn_save.clicked.connect(self._on_save_confirmed)
        self._btn_accept.clicked.connect(self._on_accept)
        self._btn_reextract.clicked.connect(self._on_reextract)
        self._btn_discard.clicked.connect(self._on_discard)
        self._btn_delete.clicked.connect(self._on_delete)

        for btn in (
            self._btn_save,
            self._btn_accept,
            self._btn_reextract,
            self._btn_discard,
            self._btn_delete,
        ):
            outer.addWidget(btn)

        return container

    def show_placeholder(self) -> None:
        self._current_record = None
        self._stack.setCurrentWidget(self._placeholder_label)

    def show_pending_record(self, record: SpellRecord) -> None:
        self._current_record = record
        spell = record.draft_spell or record.canonical_spell
        name = spell.name if spell else f"[{record.spell_id[:8]}]"
        self._pending_name_label.setText(f"Spell: {name}")
        self._pending_order_label.setText(f"Extraction order: {record.extraction_order}")
        self._pending_range_label.setText(
            f"Boundary lines: {record.boundary_start_line}-{record.boundary_end_line}"
        )
        self._stack.setCurrentWidget(self._pending_widget)

    def show_review_record(self, record: SpellRecord, session_state: SessionState) -> None:
        self._loading = True
        try:
            self._current_record = record
            self._current_session = session_state

            try:
                draft: Spell = get_review_draft(record)
            except InvalidRecordStateError:
                self.show_placeholder()
                return

            name = draft.name if isinstance(draft.name, str) else ""
            level = draft.level if isinstance(draft.level, int) else ""
            description = draft.description if isinstance(draft.description, str) else ""

            class_value: str
            raw_class = getattr(draft, "class_list", None)
            if isinstance(raw_class, str):
                class_value = raw_class
            elif isinstance(getattr(raw_class, "value", None), str):
                class_value = raw_class.value
            else:
                class_value = "Wizard"

            school = draft.school if isinstance(getattr(draft, "school", None), list) else []
            sphere = draft.sphere if isinstance(getattr(draft, "sphere", None), list) else []
            components = draft.components if isinstance(getattr(draft, "components", None), list) else []

            self._field_name.setText(name)
            self._field_level.setText(str(level))
            self._field_description.setPlainText(description)
            self._field_class_list.setCurrentText(class_value)
            self._field_school.setText(", ".join(str(item) for item in school))
            self._field_sphere.setText(", ".join(str(item) for item in sphere))
            self._field_range.setText(draft.range if isinstance(getattr(draft, "range", None), str) else "")
            self._field_casting_time.setText(
                draft.casting_time if isinstance(getattr(draft, "casting_time", None), str) else ""
            )
            self._field_duration.setText(
                draft.duration if isinstance(getattr(draft, "duration", None), str) else ""
            )
            self._field_area_of_effect.setText(
                draft.area_of_effect
                if isinstance(getattr(draft, "area_of_effect", None), str)
                else ""
            )
            self._field_saving_throw.setText(
                draft.saving_throw if isinstance(getattr(draft, "saving_throw", None), str) else ""
            )
            self._field_components.setText(
                ", ".join(comp.value if hasattr(comp, "value") else str(comp) for comp in components)
            )
            self._field_reversible.setChecked(bool(getattr(draft, "reversible", False)))
            self._field_needs_review.setChecked(bool(getattr(draft, "needs_review", False)))
            self._field_review_notes.setPlainText(
                draft.review_notes if isinstance(getattr(draft, "review_notes", None), str) else ""
            )

            self._dirty_banner.setVisible(record.draft_dirty)
            self._btn_accept.setVisible(record.status.value == "needs_review")
            self._btn_save.setVisible(record.status.value == "confirmed")
            draft_only_needs_review = (
                record.status.value == "needs_review" and record.canonical_spell is None
            )
            self._btn_discard.setEnabled(not draft_only_needs_review)
            self._btn_reextract.setEnabled(not draft_only_needs_review)
            if draft_only_needs_review:
                self._btn_discard.setToolTip(
                    "Discard is unavailable for draft-only Needs Review records. "
                    "Use Delete instead."
                )
                self._btn_reextract.setToolTip(
                    "Re-extract is unavailable for draft-only Needs Review records. "
                    "Delete this record and run extraction again."
                )
            else:
                self._btn_discard.setToolTip("")
                self._btn_reextract.setToolTip("")

            self._has_validation_errors = False
            self._stack.setCurrentWidget(self._review_widget)
        finally:
            self._loading = False

    def _on_save_confirmed(self) -> None:
        if self._current_record is None or self._current_session is None:
            return

        if not self._allow_commit_action(action_name="Save"):
            return

        try:
            conflict = get_confirmed_save_duplicate_conflict(
                self._current_session,
                spell_id=self._current_record.spell_id,
            )
        except Exception:
            self._show_backend_error(
                title="Save Failed",
                safe_message="Unable to save confirmed changes right now. Please try again.",
            )
            return

        if conflict is not None:
            QMessageBox.warning(
                self,
                "Duplicate Confirmed Spell",
                "A confirmed spell with the same name already exists. "
                "Resolve the duplicate before saving.",
            )
            return

        try:
            save_confirmed_changes(
                self._current_session,
                spell_id=self._current_record.spell_id,
                config=self._config,
            )
        except Exception:
            self._show_backend_error(
                title="Save Failed",
                safe_message="Unable to save confirmed changes right now. Please try again.",
            )
            return

        self._dirty_banner.setVisible(False)
        self.session_changed.emit(self._current_session)

    def _on_accept(self) -> None:
        if self._current_record is None or self._current_session is None:
            return

        if not self._allow_commit_action(action_name="Accept"):
            return

        try:
            committed = accept_review_record(
                self._current_session,
                spell_id=self._current_record.spell_id,
                duplicate_resolution=DuplicateResolutionStrategy.SKIP,
                config=self._config,
            )
        except Exception:
            self._show_backend_error(
                title="Accept Failed",
                safe_message="Unable to accept this spell right now. Please try again.",
            )
            return

        if committed:
            self.show_review_record(self._current_record, self._current_session)
            self.session_changed.emit(self._current_session)
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Duplicate Spell - Choose Resolution")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("A confirmed spell with the same name already exists."))

        rb_overwrite = QRadioButton("Overwrite existing confirmed spell")
        rb_keep_both = QRadioButton("Keep both (commit as-is; duplicate names remain)")
        rb_skip = QRadioButton("Skip - leave in Needs Review (do not commit)")
        rb_overwrite.setChecked(True)

        layout.addWidget(rb_overwrite)
        layout.addWidget(rb_keep_both)
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
            return

        try:
            committed = accept_review_record(
                self._current_session,
                spell_id=self._current_record.spell_id,
                duplicate_resolution=strategy,
                config=self._config,
            )
        except Exception:
            self._show_backend_error(
                title="Accept Failed",
                safe_message="Unable to accept this spell right now. Please try again.",
            )
            return

        if committed:
            self.show_review_record(self._current_record, self._current_session)
            self.session_changed.emit(self._current_session)

    def _show_backend_error(self, *, title: str, safe_message: str) -> None:
        QMessageBox.critical(self, title, safe_message)

    def _allow_commit_action(self, *, action_name: str) -> bool:
        if not self._has_validation_errors:
            return True

        QMessageBox.warning(
            self,
            f"{action_name} Blocked",
            "This form has validation errors. Fix the invalid fields before saving or accepting.",
        )
        return False

    def _on_reextract(self) -> None:
        if self._current_record is None or self._current_session is None:
            return

        if (
            self._current_record.status.value == "needs_review"
            and self._current_record.canonical_spell is None
        ):
            QMessageBox.warning(
                self,
                "Re-extract Unavailable",
                "Re-extract is unavailable for draft-only Needs Review records. "
                "Delete this record and run extraction again.",
            )
            return

        focus_prompt, ok = QInputDialog.getText(
            self,
            "Re-extract Spell",
            "Enter an optional focus prompt for the LLM:",
        )
        if not ok:
            return

        try:
            reextract_record_into_draft(
                self._current_session,
                spell_id=self._current_record.spell_id,
                focus_prompt=focus_prompt,
                config=self._config,
            )
        except Exception:
            self._show_backend_error(
                title="Re-extract Failed",
                safe_message="Unable to re-extract this spell draft right now. Please try again.",
            )
            self.show_review_record(self._current_record, self._current_session)
            return

        self.show_review_record(self._current_record, self._current_session)
        has_unsaved_changes = bool(self._current_record and self._current_record.draft_dirty)
        if has_unsaved_changes:
            self._dirty_banner.setText("Unsaved changes")
        self._dirty_banner.setVisible(has_unsaved_changes)
        self.session_changed.emit(self._current_session)

    def _on_discard(self) -> None:
        if self._current_record is None or self._current_session is None:
            return

        if (
            self._current_record.status.value == "needs_review"
            and self._current_record.canonical_spell is None
        ):
            QMessageBox.warning(
                self,
                "Discard Unavailable",
                "Discard is unavailable for draft-only Needs Review records. "
                "Use Delete instead.",
            )
            return

        try:
            discard_record_draft(self._current_record)
        except Exception:
            self._show_backend_error(
                title="Discard Failed",
                safe_message="Unable to discard this spell draft right now. Please try again.",
            )
            return

        self._dirty_banner.setVisible(False)
        if (
            self._current_record.draft_spell is None
            and self._current_record.canonical_spell is None
        ):
            self.show_placeholder()
        else:
            self.show_review_record(self._current_record, self._current_session)
        self.session_changed.emit(self._current_session)

    def _on_delete(self) -> None:
        if self._current_record is None or self._current_session is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Spell",
            "Delete this spell record? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = delete_record(self._current_session, spell_id=self._current_record.spell_id)
        except Exception:
            self._show_backend_error(
                title="Delete Failed",
                safe_message="Unable to delete this spell record right now. Please try again.",
            )
            return

        if not deleted:
            QMessageBox.warning(
                self,
                "Delete Failed",
                "Spell record could not be deleted. It may have already been removed.",
            )
            return

        self._current_record = None
        self.show_placeholder()
        self.session_changed.emit(self._current_session)

    def _on_field_edited(self) -> None:
        if self._loading:
            return
        if self._current_record is None:
            return

        class_value = self._field_class_list.currentText()
        sphere_values = _parse_csv(self._field_sphere.text())
        sphere_update: list[str] | None = sphere_values
        if class_value == "Wizard" and not sphere_values:
            sphere_update = None

        updates: dict[str, Any] = {
            "name": self._field_name.text().strip(),
            "level": self._field_level.text().strip(),
            "description": self._field_description.toPlainText().strip(),
            "class_list": class_value,
            "school": _parse_csv(self._field_school.text()),
            "sphere": sphere_update,
            "range": self._field_range.text().strip(),
            "casting_time": self._field_casting_time.text().strip(),
            "duration": self._field_duration.text().strip(),
            "area_of_effect": self._field_area_of_effect.text().strip(),
            "saving_throw": self._field_saving_throw.text().strip(),
            "components": _parse_csv(self._field_components.text()),
            "reversible": self._field_reversible.isChecked(),
            "needs_review": self._field_needs_review.isChecked(),
            "review_notes": self._field_review_notes.toPlainText().strip() or None,
        }

        try:
            apply_review_edits(self._current_record, draft_updates=updates, config=self._config)
            self._has_validation_errors = False
            self._dirty_banner.setVisible(True)
            self._dirty_banner.setText("Unsaved changes")
        except Exception as exc:
            self._has_validation_errors = True
            self._dirty_banner.setVisible(True)
            self._dirty_banner.setText(f"Invalid: {exc}")


def _parse_csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]
