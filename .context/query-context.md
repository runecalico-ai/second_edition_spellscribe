# SigMap Query Context
Generated: 2026-05-28T12:14:41.209Z

## app\pipeline\extraction.py
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
```

## app\pipeline\ingestion.py
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

## tests\test_app_config.py
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

## tests\test_session_state.py
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
```

## app\ui\review_panel.py
```
class ReviewPanel(QWidget)
def __init__(*, config: AppConfig, parent: QWidget | None) → None
def show_placeholder() → None
def show_pending_record(record: SpellRecord) → None
def show_review_record(record: SpellRecord, session_state: SessionState) → None
```
