"""Settings dialog for editing AppConfig with Save/Cancel semantics."""
from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING

try:
    import anthropic
except ImportError:  # pragma: no cover
    class _AnthropicStub:
        class Anthropic:  # type: ignore[no-redef]
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("anthropic package is not installed")

    anthropic = _AnthropicStub()  # type: ignore[assignment]
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import CREDENTIAL_ACCOUNT_NAME, CREDENTIAL_SERVICE_NAME

if TYPE_CHECKING:
    from app.config import AppConfig


class SettingsDialog(QDialog):
    """Edit app configuration and persist only on Save."""

    def __init__(self, *, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original_config = config
        self._working_config = copy.deepcopy(config)
        self.setWindowTitle("Settings")
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        form_widget = QWidget(scroll)
        form = QFormLayout(form_widget)
        scroll.setWidget(form_widget)
        outer.addWidget(scroll)

        self._field_stage1_model = QLineEdit(self._working_config.stage1_model, self)
        form.addRow("Stage 1 model:", self._field_stage1_model)

        self._field_stage2_model = QLineEdit(self._working_config.stage2_model, self)
        form.addRow("Stage 2 model:", self._field_stage2_model)

        self._field_stage1_cutoff = QSpinBox(self)
        self._field_stage1_cutoff.setRange(0, 10000)
        self._field_stage1_cutoff.setValue(self._working_config.stage1_empty_page_cutoff)
        form.addRow("Stage 1 empty-page cutoff:", self._field_stage1_cutoff)

        self._field_max_concurrent = QSpinBox(self)
        self._field_max_concurrent.setRange(1, 20)
        self._field_max_concurrent.setValue(self._working_config.max_concurrent_extractions)
        form.addRow("Max concurrent extractions:", self._field_max_concurrent)

        self._field_confidence = QDoubleSpinBox(self)
        self._field_confidence.setRange(0.0, 1.0)
        self._field_confidence.setSingleStep(0.05)
        self._field_confidence.setDecimals(2)
        self._field_confidence.setValue(self._working_config.confidence_threshold)
        form.addRow("Confidence threshold:", self._field_confidence)

        self._field_tesseract = QLineEdit(self._working_config.tesseract_path, self)
        form.addRow("Tesseract path:", self._path_row(self._field_tesseract, is_file=True))

        self._field_export_dir = QLineEdit(self._working_config.export_directory, self)
        form.addRow("Export directory:", self._path_row(self._field_export_dir, is_file=False))

        self._field_default_source = QLineEdit(self._working_config.default_source_document, self)
        form.addRow("Default source document:", self._field_default_source)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self._on_cancel)

        self._build_credential_controls(form)

        outer.addWidget(buttons)

    def _path_row(self, line_edit: QLineEdit, *, is_file: bool) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        browse_btn = QPushButton("Browse...", row)
        if is_file:
            browse_btn.clicked.connect(lambda: self._browse_file(line_edit))
        else:
            browse_btn.clicked.connect(lambda: self._browse_directory(line_edit))
        layout.addWidget(browse_btn)
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
        group = QGroupBox("API Key Source", self)
        layout = QVBoxLayout(group)

        self._rb_env = QRadioButton("Environment variable (ANTHROPIC_API_KEY)", group)
        self._rb_credential_manager = QRadioButton("Windows Credential Manager", group)
        self._rb_local_plaintext = QRadioButton("Store in config.json (plaintext)", group)

        self._radio_group = QButtonGroup(self)
        self._radio_group.addButton(self._rb_env, 0)
        self._radio_group.addButton(self._rb_credential_manager, 1)
        self._radio_group.addButton(self._rb_local_plaintext, 2)

        layout.addWidget(self._rb_env)
        layout.addWidget(self._rb_credential_manager)
        layout.addWidget(self._rb_local_plaintext)

        self._env_note_label = QLabel("Set the ANTHROPIC_API_KEY environment variable.", group)
        self._env_note_label.setStyleSheet("color: grey; font-style: italic;")
        layout.addWidget(self._env_note_label)

        key_row = QWidget(group)
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self._key_field = QLineEdit(key_row)
        self._key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_field.setPlaceholderText("API key")
        self._key_field.textChanged.connect(self._update_test_key_button_state)
        self._key_toggle_btn = QPushButton("Show", key_row)
        self._key_toggle_btn.setCheckable(True)
        self._key_toggle_btn.clicked.connect(self._toggle_key_visibility)
        key_layout.addWidget(self._key_field)
        key_layout.addWidget(self._key_toggle_btn)
        layout.addWidget(key_row)

        self._plaintext_warning = QLabel(
            "Key will be stored unencrypted in config.json without OS keyring protection.",
            group,
        )
        self._plaintext_warning.setStyleSheet("color: #c0392b; font-weight: bold;")
        self._plaintext_warning.setWordWrap(True)
        layout.addWidget(self._plaintext_warning)

        self._plaintext_confirm_check = QCheckBox(
            "I understand and accept the risk of plaintext key storage.",
            group,
        )
        self._plaintext_confirm_check.stateChanged.connect(self._update_save_button_state)
        layout.addWidget(self._plaintext_confirm_check)

        self._plaintext_error_label = QLabel("", group)
        self._plaintext_error_label.setStyleSheet("color: #c0392b;")
        self._plaintext_error_label.setVisible(False)
        layout.addWidget(self._plaintext_error_label)

        self._btn_test_key = QPushButton("Test API Key", group)
        self._btn_test_key.clicked.connect(self._on_test_api_key)
        self._test_key_result = QLabel("", group)
        layout.addWidget(self._btn_test_key)
        layout.addWidget(self._test_key_result)

        form.addRow(group)

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
        self._plaintext_error_label.setVisible(False)
        self._plaintext_error_label.setText("")

        if not is_plaintext:
            self._plaintext_confirm_check.setChecked(False)

        self._update_test_key_button_state()
        self._update_save_button_state()

    def _toggle_key_visibility(self) -> None:
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
            enabled = True
        self._btn_test_key.setEnabled(enabled)

    def _update_save_button_state(self) -> None:
        if self._rb_local_plaintext.isChecked():
            can_save = self._plaintext_confirm_check.isChecked()
        else:
            can_save = True
        self._save_button.setEnabled(can_save)

    def _on_test_api_key(self) -> None:
        try:
            if self._rb_env.isChecked():
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            elif self._rb_local_plaintext.isChecked():
                api_key = self._key_field.text().strip()
            else:
                import keyring

                api_key = keyring.get_password(
                    CREDENTIAL_SERVICE_NAME,
                    CREDENTIAL_ACCOUNT_NAME,
                ) or ""
        except Exception as exc:  # noqa: BLE001
            self._test_key_result.setText(f"Failed to load API key: {exc}")
            self._test_key_result.setStyleSheet("color: red;")
            self._update_test_key_button_state()
            return

        if not api_key:
            self._test_key_result.setText("No API key to test.")
            return

        self._btn_test_key.setEnabled(False)
        self._test_key_result.setText("Testing...")
        QApplication.processEvents()

        try:
            client = anthropic.Anthropic(api_key=api_key)
            client.models.list()
            self._test_key_result.setText("API key is valid.")
            self._test_key_result.setStyleSheet("color: green;")
        except Exception as exc:  # noqa: BLE001
            self._test_key_result.setText(f"{exc}")
            self._test_key_result.setStyleSheet("color: red;")
        finally:
            self._update_test_key_button_state()

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

    def _on_save(self) -> None:
        if self._rb_local_plaintext.isChecked() and not self._plaintext_confirm_check.isChecked():
            message = "Please confirm plaintext storage risk before saving."
            self._plaintext_error_label.setText(message)
            self._plaintext_error_label.setVisible(True)
            QMessageBox.warning(self, "Confirmation Required", message)
            return

        try:
            self._apply_fields_to_working_config()
            normalized_config = self._working_config.normalized()
            normalized_config.save()
            for field_name in vars(normalized_config):
                setattr(self._original_config, field_name, getattr(normalized_config, field_name))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save settings: {exc}",
            )
            return

        self.accept()

    def _on_cancel(self) -> None:
        self.reject()
