from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig, CREDENTIAL_ACCOUNT_NAME, CREDENTIAL_SERVICE_NAME


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


class AppConfigContractTests(unittest.TestCase):
    def test_credential_manager_constant_names_are_stable(self) -> None:
        self.assertEqual(CREDENTIAL_SERVICE_NAME, "SpellScribe")
        self.assertEqual(CREDENTIAL_ACCOUNT_NAME, "anthropic_api_key")


class AppConfigNormalizationTests(unittest.TestCase):
    def test_confidence_threshold_non_finite_values_fall_back_to_default(self) -> None:
        default_threshold = AppConfig().normalized().confidence_threshold

        for raw_value in (float("nan"), float("inf"), float("-inf"), "nan", "inf", "-inf"):
            with self.subTest(raw_value=raw_value):
                config = AppConfig.from_dict({"confidence_threshold": raw_value})
                self.assertEqual(config.confidence_threshold, default_threshold)

    def test_integer_settings_non_finite_values_fall_back_to_defaults(self) -> None:
        defaults = AppConfig().normalized()

        for raw_value in (float("nan"), float("inf"), float("-inf"), "nan", "inf", "-inf"):
            with self.subTest(raw_value=raw_value):
                config = AppConfig.from_dict(
                    {
                        "stage1_empty_page_cutoff": raw_value,
                        "max_concurrent_extractions": raw_value,
                    }
                )

                self.assertEqual(
                    config.stage1_empty_page_cutoff,
                    defaults.stage1_empty_page_cutoff,
                )
                self.assertEqual(
                    config.max_concurrent_extractions,
                    defaults.max_concurrent_extractions,
                )

    def test_force_ocr_invalid_bool_values_are_ignored(self) -> None:
        config = AppConfig.from_dict(
            {
                "force_ocr_by_sha256": {
                    SHA_A: "true",
                    SHA_B: "not-a-bool",
                    SHA_C: 2,
                }
            }
        )

        self.assertEqual(config.force_ocr_by_sha256, {SHA_A: True})

    def test_local_plaintext_api_key_sanitizes_non_string_values(self) -> None:
        config = AppConfig.from_dict(
            {
                "api_key_storage_mode": "local_plaintext",
                "api_key": 12345,
            }
        )

        self.assertIsInstance(config.api_key, str)
        self.assertEqual(config.api_key, "")

    def test_document_offsets_reject_non_integral_values(self) -> None:
        config = AppConfig.from_dict(
            {
                "document_offsets": {
                    SHA_A: 2.7,
                    SHA_B: "2.7",
                    SHA_C: 2.0,
                    SHA_D: "42",
                }
            }
        )

        self.assertEqual(config.document_offsets, {SHA_C: 2, SHA_D: 42})

    def test_stage_models_use_defaults_for_none_non_string_and_blank_values(self) -> None:
        defaults = AppConfig().normalized()

        for raw_value in (None, 123, {"model": "x"}, "", "   "):
            with self.subTest(raw_value=raw_value):
                config = AppConfig.from_dict(
                    {
                        "stage1_model": raw_value,
                        "stage2_model": raw_value,
                    }
                )

                self.assertEqual(config.stage1_model, defaults.stage1_model)
                self.assertEqual(config.stage2_model, defaults.stage2_model)

    def test_stage_models_keep_valid_non_empty_string_values(self) -> None:
        config = AppConfig.from_dict(
            {
                "stage1_model": " claude-stage1-custom ",
                "stage2_model": "claude-stage2-custom",
            }
        )

        self.assertEqual(config.stage1_model, "claude-stage1-custom")
        self.assertEqual(config.stage2_model, "claude-stage2-custom")

    def test_path_and_source_fields_use_defaults_for_none_non_string_and_blank_values(self) -> None:
        defaults = AppConfig().normalized()
        field_defaults = {
            "export_directory": defaults.export_directory,
            "tesseract_path": defaults.tesseract_path,
            "default_source_document": defaults.default_source_document,
            "last_import_directory": defaults.last_import_directory,
        }

        for field_name, default_value in field_defaults.items():
            for raw_value in (None, 123, ["x"], {"path": "x"}, "", "   "):
                with self.subTest(field_name=field_name, raw_value=raw_value):
                    config = AppConfig.from_dict({field_name: raw_value})
                    self.assertEqual(getattr(config, field_name), default_value)

    def test_path_and_source_fields_keep_valid_non_empty_string_values(self) -> None:
        config = AppConfig.from_dict(
            {
                "export_directory": "C:/tmp/exports",
                "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe",
                "default_source_document": "Arcana Compendium",
                "last_import_directory": "C:/tmp/imports",
            }
        )

        self.assertEqual(config.export_directory, "C:/tmp/exports")
        self.assertEqual(config.tesseract_path, "C:/Program Files/Tesseract-OCR/tesseract.exe")
        self.assertEqual(config.default_source_document, "Arcana Compendium")
        self.assertEqual(config.last_import_directory, "C:/tmp/imports")


class AppConfigPersistenceTests(unittest.TestCase):
    def test_load_with_non_finite_integer_values_uses_default_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage1_empty_page_cutoff": float("inf"),
                        "max_concurrent_extractions": float("inf"),
                    }
                ),
                encoding="utf-8",
            )

            loaded = AppConfig.load(config_path)
            defaults = AppConfig().normalized()

            self.assertEqual(loaded.stage1_empty_page_cutoff, defaults.stage1_empty_page_cutoff)
            self.assertEqual(loaded.max_concurrent_extractions, defaults.max_concurrent_extractions)

    def test_save_and_load_round_trip_with_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "explicit-config.json"
            config = AppConfig(
                api_key_storage_mode="local_plaintext",
                api_key="test-api-key",
                stage1_model="claude-haiku-4-5-latest",
                stage2_model="claude-sonnet-4-latest",
                custom_schools=["Runecraft", "  ", "Chronomancy"],
                custom_spheres=["Starlight", ""],
                document_offsets={SHA_A.upper(): "12", "invalid": 9},
                force_ocr_by_sha256={SHA_B.upper(): "yes", SHA_C: True, "bad": False},
            )

            destination = config.save(config_path)
            loaded = AppConfig.load(config_path)

            self.assertEqual(destination, config_path)
            self.assertEqual(loaded, config.normalized())
            self.assertEqual(loaded.document_offsets, {SHA_A: 12})
            self.assertEqual(loaded.force_ocr_by_sha256, {SHA_B: True, SHA_C: True})

    def test_load_ignores_unknown_keys_and_uses_defaults_for_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            payload = {
                "api_key_storage_mode": "credential_manager",
                "api_key": "should-not-persist",
                "custom_schools": ["Runecraft", ""],
                "document_offsets": {SHA_D: "7"},
                "force_ocr_by_sha256": {SHA_A.upper(): "on"},
                "unknown_flag": True,
                "unknown_nested": {"x": 1},
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = AppConfig.load(config_path)
            defaults = AppConfig().normalized()

            self.assertEqual(loaded.api_key_storage_mode, "credential_manager")
            self.assertEqual(loaded.api_key, "")
            self.assertEqual(loaded.custom_schools, ["Runecraft"])
            self.assertEqual(loaded.document_offsets, {SHA_D: 7})
            self.assertEqual(loaded.force_ocr_by_sha256, {SHA_A: True})
            self.assertEqual(loaded.stage1_model, defaults.stage1_model)
            self.assertEqual(loaded.max_concurrent_extractions, defaults.max_concurrent_extractions)

    def test_load_returns_normalized_defaults_and_quarantines_when_json_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            malformed_payload = '{"api_key_storage_mode": '
            config_path.write_text(malformed_payload, encoding="utf-8")

            loaded = AppConfig.load(config_path)

            self.assertEqual(loaded, AppConfig().normalized())
            self.assertFalse(config_path.exists())

            quarantined_files = list(config_path.parent.glob("config.json.bad.*"))
            self.assertEqual(len(quarantined_files), 1)
            self.assertEqual(quarantined_files[0].read_text(encoding="utf-8"), malformed_payload)

    def test_load_returns_normalized_defaults_and_quarantines_when_top_level_json_is_not_a_dict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            list_payload = ["not", "a", "dict"]
            config_path.write_text(json.dumps(list_payload), encoding="utf-8")

            loaded = AppConfig.load(config_path)

            self.assertEqual(loaded, AppConfig().normalized())
            self.assertFalse(config_path.exists())

            quarantined_files = list(config_path.parent.glob("config.json.bad.*"))
            self.assertEqual(len(quarantined_files), 1)
            self.assertEqual(
                json.loads(quarantined_files[0].read_text(encoding="utf-8")),
                list_payload,
            )

    def test_save_does_not_corrupt_existing_file_when_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            original_contents = '{"api_key_storage_mode": "env", "api_key": ""}\n'
            config_path.write_text(original_contents, encoding="utf-8")

            def failing_dump(_obj: object, handle: object, *args: object, **kwargs: object) -> None:
                del args, kwargs
                writer = handle
                writer.write('{"partial": ')
                raise RuntimeError("simulated write failure")

            with patch("app.config.json.dump", side_effect=failing_dump):
                with self.assertRaises(RuntimeError):
                    AppConfig(api_key_storage_mode="local_plaintext", api_key="new-key").save(
                        config_path
                    )

            self.assertEqual(config_path.read_text(encoding="utf-8"), original_contents)


if __name__ == "__main__":
    unittest.main()
