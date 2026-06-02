# SigMap Query Context
Generated: 2026-06-02T11:20:42.801Z

## tests\test_pipeline_export.py
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
```

## app\utils\logging_setup.py
```
class APIKeyRedactionFilter(logging.Filter)
def __init__(api_key: str | None) → None
def set_api_key(api_key: str | None) → None
def filter(record: logging.LogRecord) → bool
@dataclass LoggingSetupResult(log_file_path, redaction_filter, _claim_handle)
def setup_logging(*, logs_dir: Path | None, api_key: str | None) → LoggingSetupResult  # Configure process-wide file logging for SpellScribe
```

## tests\test_logging_setup.py
```
class APIKeyRedactionFilterTests(unittest.TestCase)
def test_filter_replaces_configured_api_key_in_message() → None
def test_filter_replaces_api_key_in_percent_formatted_args() → None
def test_filter_leaves_message_unchanged_when_key_is_empty() → None
def test_set_api_key_updates_redaction_behavior() → None
def test_filter_replaces_api_key_in_exception_traceback_text() → None
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
```

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

## app\ui\review_panel.py
```
class ReviewPanel(QWidget)
def __init__(*, config: AppConfig, parent: QWidget | None) → None
def show_placeholder() → None
def show_pending_record(record: SpellRecord) → None
def show_review_record(record: SpellRecord, session_state: SessionState) → None
```
