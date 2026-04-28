"""Tests for SettingsDialog - persistence, cancel no-op, field loading."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
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

    def test_leaving_plaintext_mode_resets_key_visibility_controls(self):
        from PySide6.QtWidgets import QLineEdit

        dlg = self._make_dialog(mode="local_plaintext")
        dlg._key_toggle_btn.click()
        self.assertEqual(dlg._key_field.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertTrue(dlg._key_toggle_btn.isChecked())
        self.assertEqual(dlg._key_toggle_btn.text(), "Hide")

        dlg._rb_env.setChecked(True)
        dlg._on_credential_mode_changed(None)

        self.assertEqual(dlg._key_field.echoMode(), QLineEdit.EchoMode.Password)
        self.assertFalse(dlg._key_toggle_btn.isChecked())
        self.assertEqual(dlg._key_toggle_btn.text(), "Show")

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

    _SANITIZED_API_TEST_FAILURE_TEXT = (
        "Unable to validate API key. Please check your configuration and try again."
    )
    _RUNTIME_REASON = "Reason: RuntimeError."
    _CLOSE_BLOCKED_TEXT = "Please wait for the API key test to finish before closing Settings."

    def _wait_until(self, predicate, timeout_ms=500) -> bool:
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            _get_app().processEvents()
            if predicate():
                return True
            QTest.qWait(5)
        _get_app().processEvents()
        return bool(predicate())

    def _patch_worker_completion(self, dlg, *, success: bool, message: str):
        call_data: dict[str, str] = {}

        def _start_worker(*, request_id: int, api_key: str) -> None:
            call_data["api_key"] = api_key
            QTimer.singleShot(
                0,
                lambda: dlg._on_api_test_finished(request_id, success, message),
            )

        return patch.object(dlg, "_start_api_key_test_worker", side_effect=_start_worker), call_data

    def _patch_worker_with_stalled_thread(self, dlg):
        call_data = {"count": 0}
        threads: list[MagicMock] = []

        def _start_worker(*, request_id: int, api_key: str) -> None:
            del request_id, api_key
            call_data["count"] += 1
            thread = MagicMock()
            worker = MagicMock()
            dlg._api_test_thread = thread
            dlg._api_test_worker = worker
            threads.append(thread)

        return (
            patch.object(dlg, "_start_api_key_test_worker", side_effect=_start_worker),
            call_data,
            threads,
        )

    def test_test_api_key_success_shows_success_label(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")

        patcher, _ = self._patch_worker_completion(
            dlg,
            success=True,
            message="API key is valid.",
        )
        with patcher:
            dlg._on_test_api_key()

            self.assertEqual(dlg._test_key_result.text(), "Testing...")
            self.assertFalse(dlg._btn_test_key.isEnabled())
            completed = self._wait_until(
                lambda: "valid" in dlg._test_key_result.text().lower(),
            )

        self.assertTrue(completed)
        self.assertIn("valid", dlg._test_key_result.text().lower())
        self.assertTrue(dlg._btn_test_key.isEnabled())

    def test_test_api_key_in_env_mode_resolves_env_key_and_shows_success(self):
        config = _make_config(api_key_storage_mode="env")
        dlg = self._make_dialog(config)

        patcher, call_data = self._patch_worker_completion(
            dlg,
            success=True,
            message="API key is valid.",
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
            with patcher:
                dlg._on_test_api_key()
                completed = self._wait_until(
                    lambda: "valid" in dlg._test_key_result.text().lower(),
                )

        self.assertTrue(completed)
        self.assertEqual(call_data["api_key"], "sk-ant-env")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_in_credential_manager_mode_resolves_key_and_shows_success(self):
        config = _make_config(api_key_storage_mode="credential_manager")
        dlg = self._make_dialog(config)
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "sk-ant-cred"

        patcher, call_data = self._patch_worker_completion(
            dlg,
            success=True,
            message="API key is valid.",
        )
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with patcher:
                dlg._on_test_api_key()
                completed = self._wait_until(
                    lambda: "valid" in dlg._test_key_result.text().lower(),
                )

        self.assertTrue(completed)
        self.assertEqual(call_data["api_key"], "sk-ant-cred")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_uses_current_unsaved_mode_selection(self):
        config = _make_config(api_key_storage_mode="env")
        dlg = self._make_dialog(config)
        dlg._rb_local_plaintext.setChecked(True)
        dlg._on_credential_mode_changed(None)
        dlg._key_field.setText("sk-ant-unsaved")

        patcher, call_data = self._patch_worker_completion(
            dlg,
            success=True,
            message="API key is valid.",
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
            with patcher:
                dlg._on_test_api_key()
                completed = self._wait_until(
                    lambda: "valid" in dlg._test_key_result.text().lower(),
                )

        self.assertTrue(completed)
        self.assertEqual(call_data["api_key"], "sk-ant-unsaved")
        self.assertIn("valid", dlg._test_key_result.text().lower())

    def test_test_api_key_failure_shows_error_label(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")

        patcher, _ = self._patch_worker_completion(
            dlg,
            success=False,
            message=self._RUNTIME_REASON,
        )
        with patcher:
            dlg._on_test_api_key()
            completed = self._wait_until(
                lambda: "Reason:" in dlg._test_key_result.text(),
            )

        self.assertTrue(completed)
        self.assertEqual(
            dlg._test_key_result.text(),
            f"{self._SANITIZED_API_TEST_FAILURE_TEXT} {self._RUNTIME_REASON}",
        )
        self.assertNotIn("token parse failure", dlg._test_key_result.text())

    def test_test_api_key_button_restores_enabled_state_rules_after_completion(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")

        captured_request: dict[str, int] = {}

        def _start_worker(*, request_id: int, api_key: str) -> None:
            captured_request["id"] = request_id

        with patch.object(dlg, "_start_api_key_test_worker", side_effect=_start_worker):
            dlg._on_test_api_key()

        self.assertEqual(dlg._test_key_result.text(), "Testing...")
        self.assertFalse(dlg._btn_test_key.isEnabled())

        dlg._key_field.setText("")
        self.assertFalse(dlg._btn_test_key.isEnabled())

        dlg._on_api_test_finished(captured_request["id"], True, "API key is valid.")
        self.assertFalse(dlg._btn_test_key.isEnabled())

    def test_test_api_key_credential_manager_keyring_failure_shows_inline_error(self):
        config = _make_config(api_key_storage_mode="credential_manager")
        dlg = self._make_dialog(config)
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = RuntimeError("backend unavailable")

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with patch("app.ui.settings_dialog.anthropic.Anthropic") as mock_anthropic:
                dlg._on_test_api_key()

        self.assertEqual(
            dlg._test_key_result.text(),
            f"{self._SANITIZED_API_TEST_FAILURE_TEXT} {self._RUNTIME_REASON}",
        )
        self.assertNotIn("backend unavailable", dlg._test_key_result.text())
        mock_anthropic.assert_not_called()

    def test_cancel_during_in_progress_api_test_requests_worker_shutdown(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")

        patcher, _call_data, threads = self._patch_worker_with_stalled_thread(dlg)
        with patcher:
            dlg._on_test_api_key()
            active_request_id = dlg._active_api_test_request_id

            dlg._on_cancel()

        self.assertEqual(len(threads), 1)
        threads[0].requestInterruption.assert_called_once()
        threads[0].quit.assert_called_once()
        threads[0].wait.assert_called_once_with(dlg._api_test_shutdown_wait_ms)
        self.assertFalse(dlg._api_test_in_progress)
        self.assertEqual(dlg._active_api_test_request_id, active_request_id + 1)

    def test_close_during_in_progress_api_test_requests_worker_shutdown(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")
        dlg.show()
        _get_app().processEvents()

        patcher, _call_data, threads = self._patch_worker_with_stalled_thread(dlg)
        with patcher:
            dlg._on_test_api_key()
            active_request_id = dlg._active_api_test_request_id

            dlg.close()
            _get_app().processEvents()

        self.assertEqual(len(threads), 1)
        threads[0].requestInterruption.assert_called_once()
        threads[0].quit.assert_called_once()
        threads[0].wait.assert_called_once_with(dlg._api_test_shutdown_wait_ms)
        self.assertFalse(dlg._api_test_in_progress)
        self.assertEqual(dlg._active_api_test_request_id, active_request_id + 1)

    def test_shutdown_api_test_worker_waits_for_thread_exit(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)

        thread = MagicMock()
        thread.wait.return_value = True
        dlg._api_test_thread = thread
        dlg._api_test_worker = MagicMock()
        dlg._api_test_in_progress = True

        did_stop = dlg._shutdown_api_test_worker(
            invalidate_request=True,
            wait_timeout_ms=321,
        )

        self.assertTrue(did_stop)
        thread.requestInterruption.assert_called_once()
        thread.quit.assert_called_once()
        thread.wait.assert_called_once_with(321)
        self.assertIsNone(dlg._api_test_thread)
        self.assertIsNone(dlg._api_test_worker)
        self.assertFalse(dlg._api_test_in_progress)

    def test_close_is_blocked_when_api_test_thread_does_not_terminate(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")
        dlg.show()
        _get_app().processEvents()

        patcher, _call_data, threads = self._patch_worker_with_stalled_thread(dlg)
        with patcher:
            dlg._on_test_api_key()
            threads[0].wait.return_value = False

            closed = dlg.close()
            _get_app().processEvents()

        self.assertFalse(closed)
        self.assertTrue(dlg.isVisible())
        self.assertEqual(dlg.result(), 0)
        self.assertEqual(dlg._test_key_result.text(), self._CLOSE_BLOCKED_TEXT)
        threads[0].requestInterruption.assert_called_once()
        threads[0].quit.assert_called_once()
        threads[0].wait.assert_called_once_with(dlg._api_test_shutdown_wait_ms)

    def test_timeout_prevents_overlap_until_prior_thread_clears(self):
        config = _make_config(api_key_storage_mode="local_plaintext")
        dlg = self._make_dialog(config)
        dlg._key_field.setText("sk-ant-test")

        patcher, call_data, threads = self._patch_worker_with_stalled_thread(dlg)
        with patcher:
            dlg._on_test_api_key()
            active_request_id = dlg._active_api_test_request_id
            self.assertEqual(call_data["count"], 1)

            dlg._on_api_test_timeout()

            self.assertFalse(dlg._api_test_in_progress)
            self.assertEqual(dlg._active_api_test_request_id, active_request_id + 1)
            self.assertEqual(dlg._test_key_result.text(), "API key test timed out. Please try again.")
            self.assertFalse(dlg._btn_test_key.isEnabled())
            threads[0].quit.assert_called_once()

            dlg._on_test_api_key()
            self.assertEqual(call_data["count"], 1)

            dlg._api_test_thread = None
            dlg._api_test_worker = None
            dlg._update_test_key_button_state()
            self.assertTrue(dlg._btn_test_key.isEnabled())

            dlg._on_test_api_key()
            self.assertEqual(call_data["count"], 2)
