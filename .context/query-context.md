# SigMap Query Context
Generated: 2026-05-02T19:13:46.801Z

## app\paths.py
```
def spellscribe_data_dir() → Path  # Return the SpellScribe application data directory
def is_frozen_runtime() → bool  # Return True when running from a frozen PyInstaller bundle
def frozen_bundle_dir() → Path | None  # Return the active PyInstaller bundle directory when availabl
def bundled_tesseract_dir() → Path | None  # Return bundled Tesseract directory for frozen builds when pr
def resolve_tesseract_executable(configured_path: str | Path | None) → str  # Resolve Tesseract executable path from user config or frozen
def resolve_tessdata_prefix(tesseract_executable: str | Path | None) → str  # Resolve tessdata root from configured executable or frozen b
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

## app\utils\review_notes.py
```
def parse_alt_tags(review_notes: str | None) → dict[str, str]  # Return ALT[field]=value tags keyed by field name
def upsert_alt_tag(review_notes: str | None, field: str, value: str) → str  # Insert or replace a single ALT[field]=value tag
def strip_alt_tags(review_notes: str | None) → str  # Remove ALT tags and normalize whitespace
```

## tests\test_review_notes.py
```
class ReviewNotesHelperTests(unittest.TestCase)
def test_parse_alt_tags_returns_last_value_per_field() → None
def test_upsert_alt_tag_replaces_existing_tag() → None
def test_strip_alt_tags_removes_all_alt_fragments() → None
def test_multiline_alt_value_round_trips_without_corrupting_notes_h001() → None
```
