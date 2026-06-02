# AGENTS.md

This file provides guidance to Agents when working with code in this repository.

## Project Overview

**SpellScribe** is a Windows desktop application that extracts AD&D 2nd Edition spell descriptions from scanned PDFs and Word documents using a two-stage Claude API pipeline:
- **Stage 1** (Boundary Detection): Claude Haiku identifies spell boundaries across document pages
- **Stage 2** (Spell Extraction): Claude Sonnet with Instructor extracts structured spell data into validated Pydantic schemas

Uncertain extractions are queued for human review in the UI before export as JSON or Markdown.

## Commands

```pwsh
# Activate virtual environment (Windows)
. .\.venv\Scripts\Activate.ps1
# Run all tests
python -m unittest discover tests/

# Run a single test file
python -m unittest tests/test_spell_models.py

# Run a single test case
python -m unittest tests.test_spell_models.TestSpellValidation.test_wizard_level_valid

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Pipeline Flow

```
Document (PDF/DOCX)
  → pipeline/detector.py    # Detect scanned vs. digital PDF
  → pipeline/ingestion.py   # Convert to Markdown + CoordinateAwareTextMap
  → [Stage 1 LLM]           # Boundary detection (not yet implemented)
  → [Stage 2 LLM]           # Spell extraction into LaxSpell (not yet implemented)
  → LaxSpell.to_spell()     # Coerce to strict Spell with validation
  → SessionState            # Track records in three-state workflow
  → [UI review]             # Human review of uncertain extractions (not yet implemented)
  → Export (JSON/Markdown)  # (not yet implemented)
```

### Key Modules

- **`app/models.py`** — Core schemas: `Spell` (strict), `LaxSpell` (lenient extraction target), `TextRegion`, `CoordinateAwareTextMap`. `Spell.model_validate()` accepts `custom_schools`/`custom_spheres` as validation context for user-learned values.
- **`app/config.py`** — `AppConfig` dataclass; persists to `%APPDATA%\SpellScribe\config.json`. API key can come from env var, Windows Credential Manager (`keyring`), or plaintext. Keyed config fields (document names, offsets, OCR overrides) use SHA-256 as key.
- **`app/session.py`** — `SessionState` + `SpellRecord` with three-state workflow: `pending_extraction → needs_review → confirmed`. Persists to `%APPDATA%\SpellScribe\session.json`.
- **`app/paths.py`** — Windows `%APPDATA%\SpellScribe` directory resolution.
- **`app/pipeline/ingestion.py`** — Routes documents to PDF/DOCX handlers; returns `RoutedDocument` with Markdown + coordinate map. OCR fallback via `pytesseract`.
- **`app/pipeline/detector.py`** — Heuristic scanned PDF detection (`text_ratio < 0.005`).
- **`app/pipeline/identity.py`** — SHA-256 file hashing for content-addressed session/config storage.

### Data Model Highlights

**`Spell`** (strict): `name`, `class_list` (Wizard/Priest), `level` (Wizard 0–9 where 0=Cantrip; Priest 1–8 where 8=Quest), `schools` (≥1), `spheres` (≥1 for Priest, None for Wizard), stat block fields, `confidence` (0.0–1.0), `needs_review`, `extraction_start_line`/`end_line`.

**`CoordinateAwareTextMap`**: Maps each Markdown line to its source location — PDF bounding box `(x0, y0, x1, y1)` or DOCX character offsets. Enables UI highlighting and page-spanning navigation.

**`SpellRecord`**: Immutable `spell_id`, mutable section order, optional `canonical_spell` (committed) + optional `draft_spell` (in-progress edits).

### Storage Patterns

- Config and session use atomic temp-file-then-replace writes for durability.
- Corrupt files are quarantined to `.bad.<UTC-timestamp>` rather than deleted.
- Session identity is content-addressed by SHA-256, surviving file moves/renames.

### Implementation Status

**Done:** Core models, `AppConfig`, `SessionState`, document ingestion pipeline, coordinate mapping, PySide6 desktop UI (main window, settings, review flow), JSON/Markdown export, test suite with fixtures, Windows packaging entry points (`build/build_all.ps1`, PyInstaller specs, Inno `build/installer.iss`; see root `README.md`).

**Not yet implemented:** Items called out as stubs in source or older docs (verify against modules before treating as missing); legacy roadmap bullets in the Architecture diagram below may lag the repo.

## Tech Stack

- **Python 3.12** for all code, use Virtual Environments (`venv`) for dependency management
- **Pydantic v2** for all schemas and validation
- **pymupdf / pymupdf4llm** for PDF text extraction and Markdown conversion
- **docx2python / python-docx** for DOCX processing
- **pytesseract** for OCR fallback on scanned PDFs
- **PySide6** for the desktop UI
- **Instructor** for structured LLM output (not yet implemented)
- **keyring** for Windows Credential Manager API key storage

## Windows-Specific Notes

- All runtime paths resolve under `%APPDATA%\SpellScribe`.
- Tesseract is expected to be bundled in the PyInstaller distribution; path configurable in `AppConfig.tesseract_path`.
- See `docs/windows-tesseract-setup.md` for local dev Tesseract installation.


## Tools

<!-- sigmap-tools -->

```json
[
  {
    "name": "sigmap_ask",
    "description": "Rank source files by relevance to a natural-language query. Run before exploring the codebase.",
    "command": "sigmap ask \"$QUERY\""
  },
  {
    "name": "sigmap_validate",
    "description": "Validate SigMap config and measure context coverage. Run after changing config or source dirs.",
    "command": "sigmap validate"
  },
  {
    "name": "sigmap_judge",
    "description": "Score an LLM response for groundedness against source context. Use to verify answer quality.",
    "command": "sigmap judge --response \"$RESPONSE\" --context \"$CONTEXT\""
  },
  {
    "name": "sigmap_query",
    "description": "Rank all files by relevance using TF-IDF and write a focused mini-context.",
    "command": "sigmap --query \"$QUERY\" --context"
  },
  {
    "name": "sigmap_weights",
    "description": "Show learned file-ranking multipliers accumulated from past sessions.",
    "command": "sigmap weights"
  }
]
```

## Auto-generated signatures
<!-- Updated by gen-context.js -->
# Code signatures

## SigMap commands

| When | Command |
|------|---------|
| Before answering a question | `sigmap ask "<your question>"` |
| After code changes | `sigmap validate` |
| To query by topic | `sigmap --query "<topic>"` |

Always run `sigmap ask` or `sigmap --query` before searching for files relevant to a task.
## deps
```
app\ui\main_window.py ← __future__, PySide6, app, fitz
app\utils\logging_setup.py ← __future__, app
tests\test_logging_setup.py ← __future__, app, unittest
tests\test_ui_main_window.py ← __future__, types, unittest, app, PySide6
app\build_config.py ← __future__
app\config.py ← __future__, app
app\models.py ← __future__, app, pydantic
app\paths.py ← __future__
app\pipeline\detector.py ← __future__
app\pipeline\export.py ← __future__, jinja2, app
app\pipeline\extraction.py ← __future__, importlib, pydantic, app
app\pipeline\identity.py ← __future__, app
app\pipeline\ingestion.py ← __future__, importlib, app
app\session.py ← __future__, pydantic, app
app\ui\document_panel.py ← __future__, PySide6
app\ui\identity_dialog.py ← __future__, PySide6, app
app\ui\review_panel.py ← __future__, PySide6, app
app\ui\settings_dialog.py ← __future__, PySide6, app
app\ui\spell_list_panel.py ← __future__, PySide6
app\ui\workers.py ← __future__, PySide6, app
app\utils\review_notes.py ← __future__
tests\test_app_config.py ← __future__, unittest, app
tests\test_build_config.py ← __future__, unittest, importlib
tests\test_coordinate_aware_text_map.py ← __future__, pydantic, app, unittest
tests\test_extract_cli.py ← __future__, unittest, app, extract_cli
tests\test_paths.py ← __future__, unittest, app
tests\test_pipeline_detector.py ← __future__, app, unittest
tests\test_pipeline_export.py ← __future__, unittest, app
tests\test_pipeline_extraction.py ← __future__, types, unittest, app, pydantic
tests\test_pipeline_ingestion.py ← __future__, unittest, docx, app, fitz
tests\test_review_notes.py ← __future__, app, unittest
tests\test_session_state.py ← __future__, pydantic, app, unittest
tests\test_spell_models.py ← __future__, pydantic, app, unittest
tests\test_ui_settings_dialog.py ← __future__, unittest
```

## app

### app\ui\main_window.py
```
class SpellScribeMainWindow(QMainWindow)
  def __init__(*, config: AppConfig, parent: QWidget | None) → None
  def closeEvent(event) → None
```

### app\utils\logging_setup.py
```
class APIKeyRedactionFilter(logging.Filter)
  def __init__(api_key: str | None) → None
  def set_api_key(api_key: str | None) → None
  def filter(record: logging.LogRecord) → bool
@dataclass LoggingSetupResult(log_file_path, redaction_filter, _claim_handle)
def setup_logging(*, logs_dir: Path | None, api_key: str | None) → LoggingSetupResult  # Configure process-wide file logging for SpellScribe
```

### app\build_config.py
```
def is_pro_build() → bool
def edition_label() → str
```

### app\config.py
```
@dataclass AppConfig(api_key_storage_mode, api_key, stage1_model, stage2_model, stage2_max_attempts, stage1_empty_page_cutoff, max_concurrent_extractions, confidence_threshold, export_directory, tesseract_path, ocr_backend, default_source_document, last_import_directory, last_export_scope, custom_schools, custom_spheres, document_names_by_sha256, document_offsets, force_ocr_by_sha256)
def default_config_path() → Path
```

### app\models.py
```
class SpellSchool(str, Enum)
class PriestSphere(str, Enum)
class ClassList(str, Enum)
class Tradition(str, Enum)
class Component(str, Enum)
class Spell(BaseModel) {name*, class_list*, level*, school*, sphere?, range*}
class LaxSpell(BaseModel) {name?, class_list?, level?, school?, sphere?, range?}
class TextRegion(BaseModel) {page?, bbox?, char_offset?}
class CoordinateAwareTextMap(BaseModel) {lines*}
```

### app\paths.py
```
def spellscribe_data_dir() → Path  # Return the SpellScribe application data directory
def spellscribe_logs_dir() → Path  # Return the SpellScribe log directory under the application d
def is_frozen_runtime() → bool  # Return True when running from a frozen PyInstaller bundle
def frozen_bundle_dir() → Path | None  # Return the active PyInstaller bundle directory when availabl
def bundled_tesseract_dir() → Path | None  # Return bundled Tesseract directory for frozen builds when pr
def resolve_tesseract_executable(configured_path: str | Path | None) → str  # Resolve Tesseract executable path from user config or frozen
def resolve_tessdata_prefix(tesseract_executable: str | Path | None) → str  # Resolve tessdata root from configured executable or frozen b
```

### app\pipeline\detector.py
```
def is_scanned_page(text_ratio: float) → bool
def should_route_pdf_to_ocr(text_ratios: Sequence[float], *, force_ocr: bool) → bool
```

### app\pipeline\export.py
```
class ExportScope(str, Enum)
def filter_records(records: list[SpellRecord], scope: ExportScope) → list[Spell]
def order_spells(records: list[SpellRecord], scope: ExportScope) → list[Spell]
def to_json(spells: list[Spell], path: str | Path, *, clean_only: bool, exported_at: str, spellscribe_version: str) → None
def to_markdown(spells: list[Spell], path: str | Path, *, clean_only: bool) → None
```

### app\pipeline\extraction.py
```
class DiscoverySpellStart(BaseModel) {spell_name?, start_line?}
class _DocumentedDiscoverySpell(BaseModel) {spell_name*, start_line?}
class _DocumentedDiscoveryPageResponse(BaseModel) {active_heading*, end_of_spells_section*, spells*}
class _LegacyDiscoveryPageResponse(BaseModel) {spell_starts*, active_heading*, end_of_spells_section*}
class DiscoveryPageResponse(BaseModel) {spell_starts?, active_heading?, end_of_spells_section?}
@dataclass DiscoveryPageInput(page_index, start_line, end_line, prior_active_heading, prompt, numbered_page_text)
@dataclass _DocumentPage(page_index, start_line, end_line, lines)
@dataclass _OpenSpellSpan(start_line, context_heading)
class DiscoveryInterruptedError(RuntimeError)
  def __init__(message: str, *, partial_session_state: SessionState) → None
@dataclass Stage2ExtractionInput(record, source_sha256_hex, source_path, boundary_start_line, boundary_end_line, context_heading, markdown_excerpt, focus_prompt?)
class DuplicateResolutionStrategy(str, Enum)
class RecordNotFoundError(LookupError)
class InvalidRecordStateError(ValueError)
class DuplicateConfirmedSpellError(ValueError)
def number_markdown_lines(lines: Sequence[str], *, start_line: int) → str
def parse_discovery_response(raw_response: str) → DiscoveryPageResponse
def detect_spells(routed_document: RoutedDocument, *, config: AppConfig, page_caller: DiscoveryPageCaller | None, session_state: SessionState | None) → SessionState
def restore_discovery_session(routed_document: RoutedDocument, *, session_path: str | Path | None) → SessionState | None
def open_or_restore_discovery_session(routed_document: RoutedDocument, *, config: AppConfig, page_caller: DiscoveryPageCaller | None, session_path: str | Path | None) → SessionState
def detect_spells_with_autosave(routed_document: RoutedDocument, *, config: AppConfig, page_caller: DiscoveryPageCaller | None, session_state: SessionState | None, session_path: str | Path | None) → SessionState
def extract_selected_pending(session_state: SessionState, *, config: AppConfig, stage2_caller: Stage2Caller | None) → SessionState
def extract_all_pending(session_state: SessionState, *, config: AppConfig, stage2_caller: Stage2Caller | None) → SessionState
def get_review_draft(record: SpellRecord) → Spell  # Return the editable draft spell for a review/confirmed recor
def apply_review_edits(record: SpellRecord, *, draft_updates: dict[str, Any], config: AppConfig) → Spell  # Apply form edits to draft only; canonical data remains uncha
```

### app\pipeline\identity.py
```
class UnknownDocumentIdentityError(RuntimeError)
  def __init__(source_sha256_hex: str)
@dataclass DocumentIdentityMetadata(source_sha256_hex, source_display_name, page_offset, force_ocr)
@dataclass DocumentIdentityInput(source_display_name, page_offset, force_ocr)
class UnknownDocumentIdentityResolver(Protocol)
def compute_sha256_hex(source_path: str | Path, *, chunk_size: int) → str
def lookup_document_identity(config: AppConfig, source_sha256_hex: str) → DocumentIdentityMetadata | ...
def resolve_document_identity(config: AppConfig, source_sha256_hex: str, *, resolver: UnknownDocumentIdentityResolver | None) → DocumentIdentityMetadata
```

### app\pipeline\ingestion.py
```
@dataclass PDFLineFragment(text, page, bbox)
@dataclass DOCXLineFragment(text, char_offset)
@dataclass PDFIngestionPayload(markdown_text, lines)
@dataclass DOCXIngestionPayload(markdown_text, lines, page_sequence?)
@dataclass RoutedDocument(source_path, source_sha256_hex, file_type, ingestion_mode, markdown_text, coordinate_map, default_source_pages, identity)
def read_pdf_text_ratios_default(source_path: Path) → list[float]
def ingest_pdf_digital_default(source_path: Path) → PDFIngestionPayload
def ingest_pdf_ocr_default(source_path: Path, *, tesseract_path: str) → PDFIngestionPayload
def ingest_docx_default(source_path: Path) → DOCXIngestionPayload
def build_pdf_coordinate_map(lines: Sequence[PDFLineFragment]) → CoordinateAwareTextMap
def build_docx_coordinate_map(lines: Sequence[DOCXLineFragment]) → CoordinateAwareTextMap
def route_document(source_path: str | Path, *, config: AppConfig, resolve_unknown_identity: UnknownIdentityResolver | None, read_pdf_text_ratios: PDFTextRatioReader | None, ingest_pdf_digital: PDFIngestor | None, ingest_pdf_ocr: PDFIngestor | None, ingest_docx: DOCXIngestor | None) → RoutedDocument
```

### app\session.py
```
class SpellRecordStatus(str, Enum)
class SpellRecord(BaseModel) {spell_id*, status*, extraction_order*, section_order*, boundary_start_line*, boundary_end_line?}
class SessionState(BaseModel) {version?, source_sha256_hex?, last_open_path*, coordinate_map*, records*, selected_spell_id?}
def default_session_path() → Path
def save_session_state(session_state: SessionState, session_path: str | Path | None) → Path
def load_session_state(session_path: str | Path | None) → SessionState | None
def restore_session_state_for_source(source_sha256_hex: str, *, session_path: str | Path | None) → SessionState | None
```

### app\ui\document_panel.py
```
class DocumentPanel(QWidget)
  def __init__(parent: QWidget | None) → None
  def show_placeholder() → None
```

### app\ui\identity_dialog.py
```
class DocumentIdentityDialog(QDialog)
  def get_result() → DocumentIdentityInput
```

### app\ui\review_panel.py
```
class ReviewPanel(QWidget)
  def __init__(*, config: AppConfig, parent: QWidget | None) → None
  def show_placeholder() → None
  def show_pending_record(record: SpellRecord) → None
  def show_review_record(record: SpellRecord, session_state: SessionState) → None
```

### app\ui\settings_dialog.py
```
class _APIKeyTestWorker(QObject)
  def __init__(*, request_id: int, api_key: str, timeout_seconds: float) → None
  def run() → None
class SettingsDialog(QDialog)
  def __init__(*, config: AppConfig, parent: QWidget | None) → None
  def done(result: int) → None
  def reject() → None
  def close() → bool
```

### app\ui\spell_list_panel.py
```
class SpellListPanel(QWidget)
  def __init__(parent: QWidget | None) → None
  def show_placeholder() → None
```

### app\ui\workers.py
```
class DetectSpellsWorker(QObject)
  def run() → None
class ExtractWorker(QObject)
  def run() → None
```

### app\utils\review_notes.py
```
def parse_alt_tags(review_notes: str | None) → dict[str, str]  # Return ALT[field]=value tags keyed by field name
def upsert_alt_tag(review_notes: str | None, field: str, value: str) → str  # Insert or replace a single ALT[field]=value tag
def strip_alt_tags(review_notes: str | None) → str  # Remove ALT tags and normalize whitespace
```

## tests

### tests\test_logging_setup.py
```
class APIKeyRedactionFilterTests(unittest.TestCase)
  def test_filter_replaces_configured_api_key_in_message() → None
  def test_filter_replaces_api_key_in_percent_formatted_args() → None
  def test_filter_leaves_message_unchanged_when_key_is_empty() → None
  def test_set_api_key_updates_redaction_behavior() → None
  def test_filter_replaces_api_key_in_exception_traceback_text() → None
class LoggingSetupImportSafetyTests(unittest.TestCase)
  def test_module_import_is_safe_when_msvcrt_is_unavailable() → None
class LogRotationTests(unittest.TestCase)
  def test_rotate_primary_log_moves_error_log_to_old_log() → None
  def test_rotate_primary_log_is_noop_when_error_log_missing() → None
class LogClaimTests(unittest.TestCase)
  def test_claim_log_file_path_returns_primary_when_available() → None
  def test_claim_log_file_path_uses_numbered_suffix_when_primary_locked() → None
  def test_claim_log_file_path_rotates_primary_before_claiming() → None
  def test_try_claim_log_file_stays_exclusive_after_file_growth() → None
class SetupLoggingTests(unittest.TestCase)
  def setUp() → None
  def tearDown() → None
  def test_setup_logging_creates_warning_level_file_with_utc_format() → None
  def test_setup_logging_skips_info_messages() → None
  def test_setup_logging_applies_redaction_filter() → None
  def test_setup_logging_records_background_thread_name() → None
  def worker() → None
  def test_setup_logging_returns_result_that_keeps_claim_alive() → None
```

### tests\test_ui_main_window.py
```
@dataclass _SpellListFixtureSpell(name)
@dataclass _SpellListFixtureRecord(spell_id, status, canonical_spell, draft_spell, section_order)
@dataclass _SpellListFixtureSession(records, selected_spell_id?)
class TestMainWindowToolbar(unittest.TestCase)
  def setUpClass() → None
  def test_window_title_shows_spellscribe_with_no_session()
  def test_toolbar_has_expected_actions()
  def test_extraction_actions_disabled_before_document_open()
  def test_open_action_always_enabled()
  def test_export_action_disabled_with_tooltip()
  def test_extraction_actions_enabled_after_session_loaded()
  def test_window_title_updates_after_session_loaded()
class TestMainWindowLoggingHelpers(unittest.TestCase)
  def test_resolve_api_key_for_redaction_returns_empty_when_unconfigured() → None
  def test_resolve_api_key_for_redaction_uses_env_var() → None
  def test_resolve_api_key_for_redaction_uses_plaintext_config() → None
  def test_init_app_logging_returns_cached_result_when_already_initialized() → None
  def test_sync_logging_redaction_is_noop_when_logging_not_initialized() → None
  def test_init_app_logging_returns_none_when_setup_raises() → None
  def test_sync_logging_redaction_updates_filter() → None
class TestMainWindowRunGui(unittest.TestCase)
  def test_run_gui_initializes_logging_before_window() → None
  def load_config() → AppConfig
  def init_logging(*args: object, **kwargs: object) → MagicMock
  def create_window(*args: object, **kwargs: object) → MagicMock
```

### tests\test_app_config.py
```
class AppConfigContractTests(unittest.TestCase)
  def test_credential_manager_constant_names_are_stable() → None
class AppConfigNormalizationTests(unittest.TestCase)
  def test_confidence_threshold_non_finite_values_fall_back_to_default() → None
  def test_integer_settings_non_finite_values_fall_back_to_defaults() → None
  def test_force_ocr_invalid_bool_values_are_ignored() → None
  def test_local_plaintext_api_key_sanitizes_non_string_values() → None
  def test_document_offsets_reject_non_integral_values() → None
  def test_stage_models_use_defaults_for_none_non_string_and_blank_values() → None
  def test_last_export_scope_uses_default_for_blank_values() → None
  def test_ocr_backend_defaults_to_tesseract_cpu() → None
class AppConfigPersistenceTests(unittest.TestCase)
  def test_load_with_non_finite_integer_values_uses_default_fallbacks() → None
  def test_last_export_scope_round_trips_and_preserves_unknown_values() → None
  def test_ocr_backend_round_trips_through_save_and_load() → None
  def test_save_and_load_round_trip_with_explicit_path() → None
  def test_load_ignores_unknown_keys_and_uses_defaults_for_missing_keys() → None
  def test_load_returns_normalized_defaults_and_quarantines_when_json_is_malformed() → None
  def test_save_does_not_corrupt_existing_file_when_write_fails() → None
  def failing_dump(_obj: object, handle: object, *args: object, **kwargs: object) → None
```

### tests\test_build_config.py
```
class BuildConfigTests(unittest.TestCase)
  def test_standard_is_default_build_flavor() → None
  def test_pro_build_flavor_uses_pro_label() → None
```

### tests\test_coordinate_aware_text_map.py
```
class TextRegionModelTests(unittest.TestCase)
  def test_pdf_text_region_round_trips_with_json_payload() → None
  def test_docx_text_region_round_trips_with_json_payload() → None
  def test_text_region_rejects_invalid_coordinate_combinations() → None
  def test_text_region_rejects_non_finite_bbox_values() → None
class CoordinateAwareTextMapModelTests(unittest.TestCase)
  def test_coordinate_map_round_trips_with_json_payload() → None
  def test_coordinate_map_safe_lookup_helpers() → None
  def test_coordinate_map_regions_for_range() → None
  def test_coordinate_map_page_span() → None
  def test_coordinate_map_range_helpers_handle_invalid_ranges() → None
  def test_coordinate_map_rejects_missing_region_links() → None
```

### tests\test_extract_cli.py
```
class ExtractCliTests(unittest.TestCase)
  def test_run_extraction_cli_uses_extract_all_by_default() → None
  def extract_all_fn(state: SessionState, *, config: AppConfig) → SessionState
  def extract_selected_fn(state: SessionState, *, config: AppConfig) → SessionState
  def save_session_fn(state: SessionState, *, session_path: str | Path | None) → Path
  def test_run_extraction_cli_uses_extract_selected_when_requested() → None
  def extract_all_fn(state: SessionState, *, config: AppConfig) → SessionState
  def extract_selected_fn(state: SessionState, *, config: AppConfig) → SessionState
  def test_run_extraction_cli_uses_returned_selected_session_state() → None
```

### tests\test_paths.py
```
class PathResolutionTests(unittest.TestCase)
  def test_resolve_tesseract_executable_prefers_configured_path() → None
  def test_resolve_tesseract_executable_falls_back_to_bundled_binary() → None
  def test_resolve_tesseract_executable_ignores_malformed_bundled_directory() → None
  def test_resolve_tessdata_prefix_detects_neighbor_directory() → None
  def test_resolve_tessdata_prefix_detects_parent_directory() → None
  def test_resolve_tessdata_prefix_ignores_malformed_tessdata_file() → None
class SpellScribeLogsDirTests(unittest.TestCase)
  def test_spellscribe_logs_dir_resolves_under_data_dir() → None
  def test_spellscribe_logs_dir_does_not_create_directory() → None
  def test_spellscribe_logs_dir_uses_data_dir_helper() → None
```

### tests\test_pipeline_detector.py
```
class ScannedDetectionTests(unittest.TestCase)
  def test_ratio_below_threshold_is_scanned() → None
  def test_ratio_equal_or_above_threshold_is_not_scanned() → None
  def test_force_ocr_override_routes_pdf_to_ocr() → None
  def test_scanned_page_routes_pdf_to_ocr_without_force_override() → None
  def test_digital_pages_without_override_stay_on_digital_path() → None
```

### tests\test_pipeline_export.py
```
class ExportHelperTests(unittest.TestCase)
  def test_filter_clean_only_returns_copy_when_disabled() → None
  def test_filter_clean_only_excludes_needs_review_when_enabled() → None
  def test_filter_clean_only_keeps_spell_with_review_notes_when_review_not_needed() → None
  def test_filter_records_excludes_pending_and_uses_canonical_only() → None
  def test_filter_records_everything_extracted_preserves_source_order() → None
  def test_filter_records_applies_scope_specific_status_filters() → None
  def test_filter_records_rejects_unsupported_scope() → None
  def test_filter_records_preserves_source_order_after_scope_filtering() → None
class ExportMarkdownTests(unittest.TestCase)
  def test_to_markdown_strips_alt_tags_and_renders_review_section_when_needed() → None
  def test_to_markdown_renders_review_section_when_review_needed_but_notes_clean_empty() → None
  def test_to_markdown_omits_review_section_for_whitespace_only_notes() → None
  def test_to_markdown_renders_description_as_standalone_paragraph() → None
  def test_to_markdown_renders_review_section_from_cleaned_notes_without_needs_review() → None
  def test_to_markdown_omits_review_section_when_review_not_needed_and_notes_clean_empty() → None
  def test_to_markdown_uses_cantrip_and_quest_labels() → None
  def test_to_markdown_clean_only_excludes_needs_review_spells() → None
class ExportJsonTests(unittest.TestCase)
  def test_to_json_preserves_integer_level_boundaries_in_v1_1_envelope() → None
  def test_to_json_preserves_non_ascii_content_across_utf_8_round_trip() → None
  def test_to_json_clean_only_excludes_needs_review_but_keeps_clean_review_notes() → None
  def test_to_json_writes_empty_v1_1_envelope_when_clean_only_filters_everything() → None
  def test_to_json_normalizes_whitespace_only_review_notes_to_null() → None
  def test_to_json_uses_atomic_write_without_leaving_tmp_files() → None
```

### tests\test_pipeline_extraction.py
```
class Stage1PromptFormattingTests(unittest.TestCase)
  def test_number_markdown_lines_uses_absolute_zero_based_line_numbers() → None
  def test_detect_spells_prompt_describes_documented_stage1_response_contract() → None
  def page_caller(page_input: DiscoveryPageInput) → DiscoveryPageResponse
  def test_detect_spells_prompt_describes_null_active_heading_as_no_heading_update() → None
  def page_caller(page_input: DiscoveryPageInput) → DiscoveryPageResponse
  def test_detect_spells_passes_prior_heading_context_into_following_page_prompt() → None
  def page_caller(page_input: DiscoveryPageInput) → DiscoveryPageResponse
class ProductionStage1RequestTests(unittest.TestCase)
class DiscoveryResponseParsingTests(unittest.TestCase)
  def test_parse_discovery_response_accepts_documented_stage1_contract() → None
  def test_parse_discovery_response_rejects_missing_required_top_level_fields() → None
  def test_discovery_page_response_rejects_duplicate_absolute_start_lines() → None
class SequentialDiscoveryTests(unittest.TestCase)
  def test_detect_spells_chunks_docx_documents_without_page_grouping_signals() → None
  def page_caller(page_input: DiscoveryPageInput) → DiscoveryPageResponse
  def test_detect_spells_skips_pending_duplicates_for_existing_non_pending_records() → None
  def test_detect_spells_skips_pending_duplicates_when_spell_id_already_exists() → None
  def test_detect_spells_preserves_caller_session_state_when_discovery_fails() → None
  def page_caller(_page_input: DiscoveryPageInput) → DiscoveryPageResponse
  def test_detect_spells_exposes_partial_pending_records_when_discovery_is_interrupted() → None
  def page_caller(_page_input: DiscoveryPageInput) → DiscoveryPageResponse
class APIKeyResolutionTests(unittest.TestCase)
  def test_read_keyring_api_key_returns_empty_string_when_backend_lookup_raises() → None
  def test_detect_spells_carries_heading_forward_and_closes_cross_page_spans() → None
```

### tests\test_pipeline_ingestion.py
```
class IngestionPipelineTests(unittest.TestCase)
  def test_configure_tesseract_binary_sets_cmd_and_tessdata_prefix() → None
  def test_configure_tesseract_binary_keeps_env_when_no_tessdata_found() → None
  def test_default_pdf_ratio_reader_reports_non_zero_text_ratio_for_text_pdf() → None
  def test_default_digital_pdf_backend_extracts_markdown_and_bounding_boxes() → None
  def test_default_ocr_pdf_backend_uses_tesseract_line_data() → None
  def test_default_docx_backend_extracts_markdown_and_character_offsets() → None
  def test_unsupported_extension_fails_fast_without_side_effects() → None
  def test_unknown_document_hash_requires_identity_metadata_before_routing() → None
class CoordinateMapFixtureTests(unittest.TestCase)
  def test_pdf_coordinate_map_generation_from_fixture() → None
  def test_pdf_coordinate_map_rejects_non_integral_page_values() → None
  def test_docx_coordinate_map_generation_from_fixture() → None
```

### tests\test_review_notes.py
```
class ReviewNotesHelperTests(unittest.TestCase)
  def test_parse_alt_tags_returns_last_value_per_field() → None
  def test_upsert_alt_tag_replaces_existing_tag() → None
  def test_strip_alt_tags_removes_all_alt_fragments() → None
  def test_multiline_alt_value_round_trips_without_corrupting_notes_h001() → None
```

### tests\test_session_state.py
```
class SessionStateSerializationTests(unittest.TestCase)
  def test_session_state_json_compatible_round_trip() → None
  def test_save_and_load_session_state_round_trip_with_explicit_path() → None
  def test_restore_session_state_for_source_returns_matching_pending_records() → None
  def test_restore_session_state_for_source_returns_none_for_hash_mismatch() → None
  def test_load_session_state_returns_none_when_file_missing() → None
  def test_load_session_state_quarantines_corrupt_json_file() → None
  def test_load_session_state_quarantines_invalid_schema_file() → None
  def test_load_session_state_accepts_supported_version() → None
class SpellRecordValidationTests(unittest.TestCase)
  def test_spell_record_allows_boundary_end_line_sentinel() → None
  def test_spell_record_rejects_negative_extraction_order() → None
  def test_spell_record_rejects_negative_section_order() → None
  def test_spell_record_rejects_negative_boundary_start_line() → None
  def test_spell_record_rejects_boundary_end_line_before_start_line() → None
  def test_spell_record_rejects_confirmed_without_canonical_spell() → None
  def test_spell_record_allows_confirmed_with_canonical_spell() → None
  def test_spell_record_rejects_dirty_draft_without_draft_spell() → None
class SessionStateInvariantTests(unittest.TestCase)
  def test_session_state_rejects_duplicate_spell_ids_in_records() → None
  def test_session_state_allows_unique_spell_ids_in_records() → None
  def test_session_state_rejects_selected_spell_id_missing_from_records() → None
  def test_session_state_allows_unset_selected_spell_id() → None
```

### tests\test_spell_models.py
```
class SpellModelValidationTests(unittest.TestCase)
  def test_wizard_cantrip_level_normalizes_to_zero() → None
  def test_priest_quest_level_normalizes_to_eight() → None
  def test_priest_spell_rejects_level_outside_supported_range() → None
  def test_priest_spell_rejects_missing_or_empty_sphere() → None
  def test_unknown_school_and_sphere_mark_review_and_append_notes() → None
  def test_custom_school_and_sphere_context_do_not_mark_review() → None
  def test_wizard_spell_rejects_non_null_sphere() → None
  def test_unknown_school_appends_note_when_existing_note_is_none_or_empty() → None
```

### tests\test_ui_settings_dialog.py
```
class TestSettingsDialogLoading(unittest.TestCase)
  def setUpClass() → None
  def test_stage1_model_field_pre_filled()
  def test_stage2_model_field_pre_filled()
  def test_confidence_threshold_field_pre_filled()
  def test_stage1_empty_page_cutoff_pre_filled()
  def test_max_concurrent_extractions_pre_filled()
  def test_export_directory_pre_filled()
  def test_tesseract_path_pre_filled()
class TestSettingsDialogPersistence(unittest.TestCase)
  def setUpClass() → None
  def test_save_writes_config_to_disk()
  def test_save_in_env_mode_clears_api_key()
  def test_save_in_credential_manager_mode_clears_api_key()
  def test_save_in_local_plaintext_mode_persists_api_key_text()
  def test_direct_on_save_in_plaintext_mode_without_confirmation_is_blocked()
  def test_save_updates_stage1_model()
  def test_save_persists_marker_ocr_backend_in_pro_build() → None
class TestCredentialControls(unittest.TestCase)
  def setUpClass() → None
  def test_env_mode_hides_key_field_shows_note()
  def test_credential_manager_mode_hides_key_field()
  def test_local_plaintext_mode_shows_key_field_and_warning()
  def test_local_plaintext_mode_shows_confirmation_checkbox()
  def test_save_blocked_in_plaintext_mode_until_confirmed()
```
