from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import UTC, datetime
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, cast

from app.paths import spellscribe_data_dir


_CONFIG_FILE_NAME = "config.json"

CREDENTIAL_SERVICE_NAME = "SpellScribe"
CREDENTIAL_ACCOUNT_NAME = "anthropic_api_key"

APIKeyStorageMode = Literal["env", "credential_manager", "local_plaintext"]


def default_config_path() -> Path:
    return spellscribe_data_dir() / _CONFIG_FILE_NAME


def _quarantine_bad_config_file(source: Path) -> None:
    if not source.exists():
        return

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    quarantined_name = f"{source.name}.bad.{timestamp}"
    quarantined_path = source.with_name(quarantined_name)

    suffix = 1
    while quarantined_path.exists():
        quarantined_path = source.with_name(f"{quarantined_name}.{suffix}")
        suffix += 1

    try:
        source.rename(quarantined_path)
    except OSError:
        pass


def _is_sha256_hex(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _coerce_storage_mode(value: Any) -> APIKeyStorageMode:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"env", "credential_manager", "local_plaintext"}:
            return cast(APIKeyStorageMode, normalized)
    return "env"


def _coerce_non_empty_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    if not normalized:
        return default
    return normalized


def _coerce_non_blank_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    if not value.strip():
        return default
    return value


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def _coerce_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


def _coerce_positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, parsed)


def _coerce_float_range(value: Any, default: float, low: float, high: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        parsed = default
    if parsed < low:
        return low
    if parsed > high:
        return high
    return parsed


def _coerce_sha_to_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, int] = {}
    for key, raw_int in value.items():
        if not isinstance(key, str):
            continue
        digest = key.strip().lower()
        if not _is_sha256_hex(digest):
            continue
        parsed = _parse_strict_int(raw_int)
        if parsed is None:
            continue
        normalized[digest] = parsed
    return normalized


def _coerce_sha_to_non_blank_string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str):
            continue
        digest = key.strip().lower()
        if not _is_sha256_hex(digest):
            continue
        if not isinstance(raw_value, str):
            continue
        display_name = raw_value.strip()
        if not display_name:
            continue
        normalized[digest] = display_name
    return normalized


def _coerce_bool(value: Any, default: bool = False) -> bool:
    parsed = _parse_optional_bool(value)
    if parsed is None:
        return default
    return parsed


def _parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None
    if isinstance(value, int):
        if value == 0:
            return False
        if value == 1:
            return True
    return None


def _parse_strict_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        sign = stripped[0] in {"+", "-"}
        digits = stripped[1:] if sign else stripped
        if not digits.isdigit():
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _coerce_sha_to_bool_map(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, bool] = {}
    for key, raw_bool in value.items():
        if not isinstance(key, str):
            continue
        digest = key.strip().lower()
        if not _is_sha256_hex(digest):
            continue
        parsed = _parse_optional_bool(raw_bool)
        if parsed is None:
            continue
        normalized[digest] = parsed
    return normalized


@dataclass
class AppConfig:
    api_key_storage_mode: APIKeyStorageMode = "env"
    api_key: str = ""
    stage1_model: str = "claude-haiku-4-5-latest"
    stage2_model: str = "claude-sonnet-4-latest"
    stage2_max_attempts: int = 3
    stage1_empty_page_cutoff: int = 10
    max_concurrent_extractions: int = 5
    confidence_threshold: float = 0.85
    export_directory: str = str(Path.home() / "Documents")
    tesseract_path: str = ""
    default_source_document: str = "Player's Handbook"
    last_import_directory: str = ""
    custom_schools: list[str] = field(default_factory=list)
    custom_spheres: list[str] = field(default_factory=list)
    document_names_by_sha256: dict[str, str] = field(default_factory=dict)
    document_offsets: dict[str, int] = field(default_factory=dict)
    force_ocr_by_sha256: dict[str, bool] = field(default_factory=dict)

    def normalized(self) -> AppConfig:
        mode = _coerce_storage_mode(self.api_key_storage_mode)
        plaintext_api_key = ""
        if mode == "local_plaintext" and isinstance(self.api_key, str):
            plaintext_api_key = self.api_key

        return AppConfig(
            api_key_storage_mode=mode,
            api_key=plaintext_api_key,
            stage1_model=_coerce_non_empty_string(
                self.stage1_model,
                default="claude-haiku-4-5-latest",
            ),
            stage2_model=_coerce_non_empty_string(
                self.stage2_model,
                default="claude-sonnet-4-latest",
            ),
            stage2_max_attempts=_coerce_positive_int(
                self.stage2_max_attempts,
                default=3,
            ),
            stage1_empty_page_cutoff=_coerce_non_negative_int(
                self.stage1_empty_page_cutoff,
                default=10,
            ),
            max_concurrent_extractions=_coerce_positive_int(
                self.max_concurrent_extractions,
                default=5,
            ),
            confidence_threshold=_coerce_float_range(
                self.confidence_threshold,
                default=0.85,
                low=0.0,
                high=1.0,
            ),
            export_directory=_coerce_non_blank_string(
                self.export_directory,
                default=str(Path.home() / "Documents"),
            ),
            tesseract_path=_coerce_non_blank_string(
                self.tesseract_path,
                default="",
            ),
            default_source_document=_coerce_non_blank_string(
                self.default_source_document,
                default="Player's Handbook",
            ),
            last_import_directory=_coerce_non_blank_string(
                self.last_import_directory,
                default="",
            ),
            custom_schools=_coerce_string_list(self.custom_schools),
            custom_spheres=_coerce_string_list(self.custom_spheres),
            document_names_by_sha256=_coerce_sha_to_non_blank_string_map(
                self.document_names_by_sha256
            ),
            document_offsets=_coerce_sha_to_int_map(self.document_offsets),
            force_ocr_by_sha256=_coerce_sha_to_bool_map(self.force_ocr_by_sha256),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {item.name: getattr(normalized, item.name) for item in fields(AppConfig)}

    def save(self, config_path: str | Path | None = None) -> Path:
        destination = Path(config_path) if config_path is not None else default_config_path()
        destination.parent.mkdir(parents=True, exist_ok=True)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(self.to_dict(), handle, ensure_ascii=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp_path, destination)
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        return destination

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AppConfig:
        known_fields = {item.name for item in fields(cls)}
        filtered_payload = {key: value for key, value in payload.items() if key in known_fields}
        return cls(**filtered_payload).normalized()

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> AppConfig:
        source = Path(config_path) if config_path is not None else default_config_path()

        if not source.exists():
            return cls().normalized()

        try:
            with source.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError:
            return cls().normalized()
        except (json.JSONDecodeError, UnicodeDecodeError):
            _quarantine_bad_config_file(source)
            return cls().normalized()

        if not isinstance(payload, dict):
            _quarantine_bad_config_file(source)
            return cls().normalized()

        return cls.from_dict(payload)