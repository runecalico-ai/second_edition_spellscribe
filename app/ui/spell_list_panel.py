"""Three-section spell list panel: Confirmed | Needs Review | Pending."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from app.session import SessionState, SpellRecord


_USER_ROLE = Qt.ItemDataRole.UserRole
_USE_CURRENT_SELECTION = object()


class SpellListPanel(QWidget):
    """Center panel: three status buckets for spell records."""

    selected_spell_id_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.show()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._placeholder_label = QLabel("Open a document to begin.", self)
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder_label)

        layout.addWidget(QLabel("Confirmed"))
        self._confirmed_list = QListWidget(self)
        self._confirmed_list.itemSelectionChanged.connect(
            lambda: self._on_selection_changed(self._confirmed_list)
        )
        layout.addWidget(self._confirmed_list)

        layout.addWidget(QLabel("Needs Review"))
        self._needs_review_list = QListWidget(self)
        self._needs_review_list.itemSelectionChanged.connect(
            lambda: self._on_selection_changed(self._needs_review_list)
        )
        layout.addWidget(self._needs_review_list)

        layout.addWidget(QLabel("Pending Extraction"))
        self._pending_list = QListWidget(self)
        self._pending_list.itemSelectionChanged.connect(
            lambda: self._on_selection_changed(self._pending_list)
        )
        layout.addWidget(self._pending_list)

        self.show_placeholder()

    def show_placeholder(self) -> None:
        self._placeholder_label.setVisible(True)

    def refresh(
        self,
        session_state: SessionState,
        *,
        selected_spell_id: str | None | object = _USE_CURRENT_SELECTION,
    ) -> str | None:
        explicit_selection = selected_spell_id is not _USE_CURRENT_SELECTION
        target_spell_id = (
            self._current_selected_spell_id()
            if selected_spell_id is _USE_CURRENT_SELECTION
            else selected_spell_id
        )
        self._placeholder_label.setVisible(False)
        items_by_spell_id: dict[str, QListWidgetItem] = {}
        list_widgets = (self._confirmed_list, self._needs_review_list, self._pending_list)
        blockers = [QSignalBlocker(list_widget) for list_widget in list_widgets]

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
            item = self._add_item(self._confirmed_list, record, _record_display_name(record))
            items_by_spell_id[record.spell_id] = item
        for record in needs_review:
            item = self._add_item(self._needs_review_list, record, _record_display_name(record))
            items_by_spell_id[record.spell_id] = item
        for record in pending:
            item = self._add_item(
                self._pending_list,
                record,
                f"[Pending] {record.spell_id[:8]}",
            )
            items_by_spell_id[record.spell_id] = item

        restored_selection = False
        if isinstance(target_spell_id, str) and target_spell_id:
            selected_item = items_by_spell_id.get(target_spell_id)
            if selected_item is not None:
                selected_item.listWidget().setCurrentItem(selected_item)
                restored_selection = True

        del blockers

        if (
            isinstance(target_spell_id, str)
            and target_spell_id
            and not restored_selection
            and not explicit_selection
        ):
            self.selected_spell_id_changed.emit("")

        if restored_selection and isinstance(target_spell_id, str):
            return target_spell_id
        return None

    def _add_item(
        self,
        list_widget: QListWidget,
        record: SpellRecord,
        label: str,
    ) -> QListWidgetItem:
        item = QListWidgetItem(label)
        item.setData(_USER_ROLE, record.spell_id)
        list_widget.addItem(item)
        return item

    def _current_selected_spell_id(self) -> str | None:
        for list_widget in (self._confirmed_list, self._needs_review_list, self._pending_list):
            selected_items = list_widget.selectedItems()
            if selected_items:
                return selected_items[0].data(_USER_ROLE)
        return None

    def _on_selection_changed(self, source_list: QListWidget) -> None:
        selected = source_list.selectedItems()
        if not selected:
            any_selected = any(
                lst.selectedItems()
                for lst in (self._confirmed_list, self._needs_review_list, self._pending_list)
            )
            if not any_selected:
                self.selected_spell_id_changed.emit("")
            return

        for other in (self._confirmed_list, self._needs_review_list, self._pending_list):
            if other is not source_list:
                other.clearSelection()

        spell_id = selected[0].data(_USER_ROLE)
        self.selected_spell_id_changed.emit(spell_id)


def _record_display_name(record: SpellRecord) -> str:
    spell = record.draft_spell or record.canonical_spell
    if spell is not None:
        return spell.name
    return f"[{record.spell_id[:8]}]"
