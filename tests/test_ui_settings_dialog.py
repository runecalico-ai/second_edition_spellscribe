"""Tests for SettingsDialog - persistence, cancel no-op, field loading."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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
    for key, value in overrides.items():
        setattr(config, key, value)
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

    def test_save_in_env_mode_clears_api_key(self):
        config = _make_config(api_key_storage_mode="local_plaintext", api_key="sk-ant-old")
        dlg = self._make_dialog(config)
        dlg._rb_env.setChecked(True)

        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()

        self.assertEqual(config.api_key_storage_mode, "env")
        self.assertEqual(config.api_key, "")

    def test_save_in_credential_manager_mode_clears_api_key(self):
        config = _make_config(api_key_storage_mode="local_plaintext", api_key="sk-ant-old")
        dlg = self._make_dialog(config)
        dlg._rb_credential_manager.setChecked(True)

        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()

        self.assertEqual(config.api_key_storage_mode, "credential_manager")
        self.assertEqual(config.api_key, "")

    def test_save_in_local_plaintext_mode_persists_api_key_text(self):
        config = _make_config(api_key_storage_mode="env", api_key="")
        dlg = self._make_dialog(config)
        dlg._rb_local_plaintext.setChecked(True)
        dlg._plaintext_confirm_check.setChecked(True)
        dlg._key_field.setText("  sk-ant-new  ")

        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()

        self.assertEqual(config.api_key_storage_mode, "local_plaintext")
        self.assertEqual(config.api_key, "sk-ant-new")

    def test_direct_on_save_in_plaintext_mode_without_confirmation_is_blocked(self):
        config = _make_config(api_key_storage_mode="local_plaintext", api_key="")
        dlg = self._make_dialog(config)
        dlg._rb_local_plaintext.setChecked(True)
        dlg._plaintext_confirm_check.setChecked(False)
        dlg._key_field.setText("sk-ant-new")

        with patch.object(dlg._working_config.__class__, "save") as mock_save:
            with patch("app.ui.settings_dialog.QMessageBox.warning") as mock_warning:
                dlg._on_save()

        mock_save.assert_not_called()
        mock_warning.assert_called_once()
        self.assertIn("confirm", dlg._plaintext_error_label.text().lower())
        self.assertEqual(dlg.result(), 0)
        self.assertEqual(config.api_key, "")

    def test_save_updates_stage1_model(self):
        config = _make_config()
        dlg = self._make_dialog(config)
        dlg._field_stage1_model.setText("changed-model")
        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()
        self.assertEqual(config.stage1_model, "changed-model")

    def test_save_applies_normalized_default_when_stage1_model_is_whitespace(self):
        from app.config import AppConfig

        config = _make_config(stage1_model="initial-model")
        dlg = self._make_dialog(config)
        dlg._field_stage1_model.setText("   ")

        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()

        self.assertEqual(config.stage1_model, AppConfig().normalized().stage1_model)

    def test_save_round_trip_updates_all_task9_fields_with_normalization(self):
        from app.config import AppConfig

        config = _make_config(
            stage1_model="old-stage1",
            stage2_model="old-stage2",
            stage1_empty_page_cutoff=1,
            max_concurrent_extractions=2,
            confidence_threshold=0.25,
            tesseract_path="C:/old/tesseract.exe",
            export_directory="C:/old/exports",
            default_source_document="Old Source",
        )
        dlg = self._make_dialog(config)

        dlg._field_stage1_model.setText("  tuned-haiku  ")
        dlg._field_stage2_model.setText("   ")
        dlg._field_stage1_cutoff.setValue(33)
        dlg._field_max_concurrent.setValue(7)
        dlg._field_confidence.setValue(0.65)
        dlg._field_tesseract.setText("  C:/tools/tesseract.exe  ")
        dlg._field_export_dir.setText("   ")
        dlg._field_default_source.setText("  Tome of Magic  ")

        with patch.object(dlg._working_config.__class__, "save"):
            dlg._on_save()

        defaults = AppConfig().normalized()
        self.assertEqual(config.stage1_model, "tuned-haiku")
        self.assertEqual(config.stage2_model, defaults.stage2_model)
        self.assertEqual(config.stage1_empty_page_cutoff, 33)
        self.assertEqual(config.max_concurrent_extractions, 7)
        self.assertAlmostEqual(config.confidence_threshold, 0.65, places=2)
        self.assertEqual(config.tesseract_path, "C:/tools/tesseract.exe")
        self.assertEqual(config.export_directory, defaults.export_directory)
        self.assertEqual(config.default_source_document, "Tome of Magic")

    def test_save_exception_keeps_dialog_open_and_preserves_original_config(self):
        config = _make_config(stage1_model="original-model")
        dlg = self._make_dialog(config)
        dlg._field_stage1_model.setText("changed-model")

        with patch.object(
            dlg._working_config.__class__,
            "save",
            side_effect=RuntimeError("disk write failed"),
        ):
            with patch("app.ui.settings_dialog.QMessageBox.critical") as mock_critical:
                dlg._on_save()

        mock_critical.assert_called_once()
        self.assertEqual(dlg.result(), 0)
        self.assertEqual(config.stage1_model, "original-model")

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

    def test_escape_cancels_without_saving_and_preserves_original_config(self):
        config = _make_config(stage2_model="original-model")
        dlg = self._make_dialog(config)
        dlg._field_stage2_model.setText("modified-model")
        dlg.show()
        _get_app().processEvents()

        with patch.object(dlg._working_config.__class__, "save") as mock_save:
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
            _get_app().processEvents()

        mock_save.assert_not_called()
        self.assertEqual(config.stage2_model, "original-model")


class TestCredentialControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _make_dialog(self, mode="env"):
        from app.ui.settings_dialog import SettingsDialog

        config = _make_config(api_key_storage_mode=mode)
        dialog = SettingsDialog(config=config)
        dialog.show()
        _get_app().processEvents()
        return dialog

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
        dlg._plaintext_confirm_check.setChecked(False)
        self.assertFalse(dlg._save_button.isEnabled())

    def test_save_enabled_in_plaintext_mode_when_confirmed(self):
        dlg = self._make_dialog(mode="local_plaintext")
        dlg._plaintext_confirm_check.setChecked(True)
        self.assertTrue(dlg._save_button.isEnabled())

    def test_show_hide_toggle_reveals_key_field_text(self):
        from PySide6.QtWidgets import QLineEdit

        dlg = self._make_dialog(mode="local_plaintext")
        self.assertEqual(dlg._key_field.echoMode(), QLineEdit.EchoMode.Password)
        dlg._toggle_key_visibility()
        self.assertEqual(dlg._key_field.echoMode(), QLineEdit.EchoMode.Normal)

    def test_test_api_key_disabled_in_env_mode_when_var_not_set(self):
        dlg = self._make_dialog(mode="env")
        with patch.dict("os.environ", {}, clear=True):
            import os as _os

            _os.environ.pop("ANTHROPIC_API_KEY", None)
            dlg._update_test_key_button_state()
        self.assertFalse(dlg._btn_test_key.isEnabled())

    def test_test_api_key_enabled_in_env_mode_when_var_set(self):
        dlg = self._make_dialog(mode="env")
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
            dlg._update_test_key_button_state()
        self.assertTrue(dlg._btn_test_key.isEnabled())

    def test_test_api_key_enabled_in_credential_manager_mode(self):
        dlg = self._make_dialog(mode="credential_manager")
        dlg._update_test_key_button_state()
        self.assertTrue(dlg._btn_test_key.isEnabled())

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
        dlg._key_field.setText("sk-ant-test")
        with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = MagicMock()
            dlg._on_test_api_key()
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_in_env_mode_resolves_env_key_and_shows_success(self):
        config = _make_config(api_key_storage_mode="env")
        dlg = self._make_dialog(config)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
            with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_client.models.list.return_value = MagicMock()
                dlg._on_test_api_key()

        mock_cls.assert_called_once_with(api_key="sk-ant-env")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_in_credential_manager_mode_resolves_key_and_shows_success(self):
        config = _make_config(api_key_storage_mode="credential_manager")
        dlg = self._make_dialog(config)
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "sk-ant-cred"

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_client.models.list.return_value = MagicMock()
                dlg._on_test_api_key()

        mock_cls.assert_called_once_with(api_key="sk-ant-cred")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_uses_current_unsaved_mode_selection(self):
        config = _make_config(api_key_storage_mode="env")
        dlg = self._make_dialog(config)
        dlg._rb_local_plaintext.setChecked(True)
        dlg._on_credential_mode_changed(None)
        dlg._key_field.setText("sk-ant-unsaved")

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
            with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_client.models.list.return_value = MagicMock()
                dlg._on_test_api_key()

        mock_cls.assert_called_once_with(api_key="sk-ant-unsaved")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_failure_shows_error_label(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")
        with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.models.list.side_effect = Exception("invalid_api_key")
            dlg._on_test_api_key()
        self.assertIn("invalid_api_key", dlg._test_key_result.text())

    def test_test_api_key_credential_manager_keyring_failure_shows_inline_error(self):
        config = _make_config(api_key_storage_mode="credential_manager")
        dlg = self._make_dialog(config)
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = RuntimeError("backend unavailable")

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_anthropic:
                dlg._on_test_api_key()

        self.assertIn("Failed to load API key", dlg._test_key_result.text())
        self.assertIn("backend unavailable", dlg._test_key_result.text())
        mock_anthropic.assert_not_called()
