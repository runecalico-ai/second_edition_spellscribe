from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import AppConfig
from app.models import ClassList, CoordinateAwareTextMap, Spell, TextRegion
from app.pipeline.extraction import (
    DuplicateConfirmedSpellError,
    DuplicateResolutionStrategy,
    DiscoveryInterruptedError,
    DiscoveryPageInput,
    DiscoveryPageResponse,
    DiscoverySpellStart,
    InvalidRecordStateError,
    RecordNotFoundError,
    Stage2ExtractionInput,
    _build_stage1_prompt_from_numbered_page,
    _read_keyring_api_key,
    _resolve_anthropic_api_key,
    accept_review_record,
    apply_review_edits,
    delete_record,
    detect_spells,
    detect_spells_with_autosave,
    discard_record_draft,
    extract_all_pending,
    extract_selected_pending,
    get_review_draft,
    get_confirmed_save_duplicate_conflict,
    number_markdown_lines,
    open_or_restore_discovery_session,
    parse_discovery_response,
    reextract_record_into_draft,
    restore_discovery_session,
    save_confirmed_changes,
)
from app.pipeline.identity import DocumentIdentityMetadata
from app.pipeline.ingestion import RoutedDocument
from app.session import SessionState, SpellRecord, SpellRecordStatus, load_session_state, save_session_state
from app.utils.review_notes import parse_alt_tags
from pydantic import ValidationError


SHA_DISCOVERY = "a" * 64


def _spell_payload(
    *,
    name: str,
    level: int,
    start_line: int,
    end_line: int,
) -> dict[str, object]:
    return {
        "name": name,
        "class_list": ClassList.WIZARD,
        "level": level,
        "school": ["Evocation"],
        "range": "30 yards",
        "components": ["V", "S"],
        "duration": "1 round",
        "casting_time": "1",
        "area_of_effect": "1 creature",
        "saving_throw": "None",
        "description": f"{name} description.",
        "source_document": "Player's Handbook",
        "source_page": 112,
        "extraction_start_line": start_line,
        "extraction_end_line": end_line,
    }


def _canonical_spell(
    *,
    name: str,
    level: int,
    start_line: int,
    end_line: int,
) -> Spell:
    return Spell.model_validate(
        _spell_payload(
            name=name,
            level=level,
            start_line=start_line,
            end_line=end_line,
        )
    )


def _build_routed_document(page_lines: list[list[str]]) -> RoutedDocument:
    coordinate_lines: list[tuple[str, TextRegion]] = []
    markdown_lines: list[str] = []
    default_source_pages: list[int | None] = []

    for page_index, lines in enumerate(page_lines):
        for line_index, line in enumerate(lines):
            markdown_lines.append(line)
            coordinate_lines.append(
                (
                    line,
                    TextRegion(
                        page=page_index,
                        bbox=(0.0, float(line_index), 100.0, float(line_index + 1)),
                    ),
                )
            )
            default_source_pages.append(page_index + 1)

    return RoutedDocument(
        source_path=Path(r"C:\\tmp\\spellbook.pdf"),
        source_sha256_hex=SHA_DISCOVERY,
        file_type="pdf",
        ingestion_mode="pdf_digital",
        markdown_text="\n".join(markdown_lines),
        coordinate_map=CoordinateAwareTextMap(lines=coordinate_lines),
        default_source_pages=default_source_pages,
        identity=DocumentIdentityMetadata(
            source_sha256_hex=SHA_DISCOVERY,
            source_display_name="Player's Handbook",
            page_offset=0,
            force_ocr=False,
        ),
    )


def _build_docx_routed_document(lines: list[str]) -> RoutedDocument:
    coordinate_lines: list[tuple[str, TextRegion]] = []
    cursor = 0

    for line in lines:
        coordinate_lines.append(
            (
                line,
                TextRegion(
                    page=-1,
                    char_offset=(cursor, cursor + len(line)),
                ),
            )
        )
        cursor += len(line) + 1

    return RoutedDocument(
        source_path=Path(r"C:\\tmp\\spellbook.docx"),
        source_sha256_hex=SHA_DISCOVERY,
        file_type="docx",
        ingestion_mode="docx",
        markdown_text="\n".join(lines),
        coordinate_map=CoordinateAwareTextMap(lines=coordinate_lines),
        default_source_pages=[None] * len(lines),
        identity=DocumentIdentityMetadata(
            source_sha256_hex=SHA_DISCOVERY,
            source_display_name="Wizard's Spell Compendium",
            page_offset=0,
            force_ocr=False,
        ),
    )


class Stage1PromptFormattingTests(unittest.TestCase):
    def test_number_markdown_lines_uses_absolute_zero_based_line_numbers(self) -> None:
        numbered = number_markdown_lines(["Magic Missile", "Range: 60 yards"], start_line=4)

        self.assertEqual(numbered, "4: Magic Missile\n5: Range: 60 yards")

    def test_detect_spells_prompt_describes_documented_stage1_response_contract(self) -> None:
        routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
        page_inputs: list[DiscoveryPageInput] = []

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return parse_discovery_response(
                """{
                    \"active_heading\": \"Wizard Spells\",
                    \"end_of_spells_section\": false,
                    \"spells\": [{\"spell_name\": \"Magic Missile\", \"start_line\": \"001\"}]
                }"""
            )

        detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(len(page_inputs), 1)
        self.assertIn('"spells"', page_inputs[0].prompt)
        self.assertIn('"spell_name"', page_inputs[0].prompt)
        self.assertIn('"active_heading": null', page_inputs[0].prompt)
        self.assertNotIn('"spell_starts"', page_inputs[0].prompt)

    def test_detect_spells_prompt_describes_null_active_heading_as_no_heading_update(self) -> None:
        routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
        page_inputs: list[DiscoveryPageInput] = []

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return DiscoveryPageResponse()

        detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(len(page_inputs), 1)
        self.assertIn(
            "Return active_heading when the current page introduces a spell-section heading or replaces the carried heading.",
            page_inputs[0].prompt,
        )
        self.assertIn(
            "Return null for active_heading when this page does not introduce a heading update. Returning null keeps prior_active_heading unchanged.",
            page_inputs[0].prompt,
        )
        self.assertNotIn(
            "Return active_heading whenever the current spell section heading still applies to this page, even if the heading text appeared on an earlier page.",
            page_inputs[0].prompt,
        )
        self.assertNotIn(
            "Return null for active_heading only when no spell-section heading applies to the page.",
            page_inputs[0].prompt,
        )

    def test_detect_spells_passes_prior_heading_context_into_following_page_prompt(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Damage: 1d4+1", "Shield"],
            ]
        )
        page_inputs: list[DiscoveryPageInput] = []
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=4)],
                    active_heading="Wizard Spells",
                ),
            ]
        )

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return next(page_responses)

        detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(len(page_inputs), 2)
        self.assertIn('"prior_active_heading": null', page_inputs[0].prompt)
        self.assertIn('"prior_active_heading": "Wizard Spells"', page_inputs[1].prompt)
        self.assertIn(
            "Use prior_active_heading as carry-forward context from the previous page.",
            page_inputs[1].prompt,
        )


class ProductionStage1RequestTests(unittest.TestCase):
    def test_default_caller_uses_documented_stage1_system_prompt_and_framed_user_message(
        self,
    ) -> None:
        routed_document = _build_routed_document([[["Wizard Spells", "Magic Missile"]][0]])
        captured_requests: list[dict[str, object]] = []
        fake_message = SimpleNamespace(
            content=[
                {
                    "text": '{"active_heading": "Wizard Spells", "end_of_spells_section": false, "spells": []}'
                }
            ]
        )
        fake_client = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **kwargs: captured_requests.append(kwargs) or fake_message
            )
        )
        fake_anthropic_module = SimpleNamespace(Anthropic=lambda api_key: fake_client)

        with patch(
            "app.pipeline.extraction._load_optional_module",
            return_value=fake_anthropic_module,
        ), patch(
            "app.pipeline.extraction._resolve_anthropic_api_key",
            return_value="test-key",
        ):
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
            )

        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(request["model"], "claude-haiku-4-5-latest")

        system_blocks = request.get("system")
        self.assertIsInstance(system_blocks, list)
        self.assertEqual(len(system_blocks), 1)
        if not isinstance(system_blocks, list):
            self.fail("Expected Anthropic system prompt blocks to be sent.")
        self.assertEqual(system_blocks[0]["type"], "text")
        self.assertEqual(system_blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertIn(
            "You are a parser for Advanced Dungeons & Dragons 2nd Edition spell books.",
            system_blocks[0]["text"],
        )

        messages = request.get("messages")
        self.assertIsInstance(messages, list)
        if not isinstance(messages, list):
            self.fail("Expected Anthropic user message list to be sent.")
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(
            messages,
            [
                {
                    "role": "user",
                    "content": message["content"],
                }
            ],
        )
        user_message = message["content"]
        self.assertIsInstance(user_message, str)
        if not isinstance(user_message, str):
            self.fail("Expected Anthropic user message content to be a string.")
        self.assertEqual(
            user_message,
            _build_stage1_prompt_from_numbered_page(
                "0: Wizard Spells\n1: Magic Missile",
                prior_active_heading=None,
            ),
        )
        self.assertNotIn("//", user_message)
        self.assertIn(
            '{"active_heading": null, "end_of_spells_section": false, "spells": [{"spell_name": "Magic Missile", "start_line": "001"}]}',
            user_message,
        )
        self.assertIn("Always include all three top-level keys.", user_message)


class DiscoveryResponseParsingTests(unittest.TestCase):
    def test_parse_discovery_response_accepts_documented_stage1_contract(self) -> None:
        response = parse_discovery_response(
            """```json
            {
              \"spells\": [
                {\"spell_name\": \"Magic Missile\", \"start_line\": \"004\"},
                {\"spell_name\": \"Shield\", \"start_line\": \"012\"}
              ],
              \"active_heading\": \"Wizard Spells\",
              \"end_of_spells_section\": false
            }
            ```"""
        )

        self.assertEqual(
            [item.model_dump() for item in response.spell_starts],
            [
                {"spell_name": "Magic Missile", "start_line": 4},
                {"spell_name": "Shield", "start_line": 12},
            ],
        )
        self.assertEqual([item.start_line for item in response.spell_starts], [4, 12])
        self.assertEqual(response.active_heading, "Wizard Spells")
        self.assertFalse(response.end_of_spells_section)

    def test_parse_discovery_response_rejects_boolean_start_line_in_documented_payload(
        self,
    ) -> None:
        with self.assertRaises(ValidationError) as caught:
            parse_discovery_response(
                """{
                    "spells": [{"spell_name": "Magic Missile", "start_line": true}],
                    "active_heading": "Wizard Spells",
                    "end_of_spells_section": false
                }"""
            )

        self.assertIn("start_line", str(caught.exception))
        self.assertIn("boolean", str(caught.exception))

    def test_parse_discovery_response_rejects_boolean_start_line_in_legacy_payload(
        self,
    ) -> None:
        with self.assertRaises(ValidationError) as caught:
            parse_discovery_response(
                """{
                    "spell_starts": [{"spell_name": "Magic Missile", "start_line": false}],
                    "active_heading": "Wizard Spells",
                    "end_of_spells_section": false
                }"""
            )

        self.assertIn("start_line", str(caught.exception))
        self.assertIn("boolean", str(caught.exception))

    def test_parse_discovery_response_rejects_missing_required_top_level_fields(self) -> None:
        with self.assertRaises(ValidationError):
            parse_discovery_response("{}")

    def test_discovery_page_response_rejects_duplicate_absolute_start_lines(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            DiscoveryPageResponse(
                spell_starts=[
                    DiscoverySpellStart(start_line=4),
                    DiscoverySpellStart(start_line=4),
                ]
            )

        self.assertIn("duplicate start_line", str(caught.exception))


class SequentialDiscoveryTests(unittest.TestCase):
    def test_detect_spells_chunks_docx_documents_without_page_grouping_signals(self) -> None:
        routed_document = _build_docx_routed_document(
            [f"Spell line {line_index}" for line_index in range(240)]
        )
        page_inputs: list[DiscoveryPageInput] = []

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return DiscoveryPageResponse()

        detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertGreater(len(page_inputs), 1)
        self.assertEqual(page_inputs[0].start_line, 0)
        self.assertGreater(page_inputs[1].start_line, page_inputs[0].start_line)
        self.assertLess(page_inputs[0].end_line, len(routed_document.coordinate_map.lines))

    def test_detect_spells_skips_pending_duplicates_for_existing_non_pending_records(self) -> None:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Shield"]]
        )
        existing_spell_id = f"pending-{SHA_DISCOVERY}-000001"
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id=existing_spell_id,
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=1,
                    boundary_end_line=2,
                    context_heading="Wizard Spells",
                    canonical_spell=_canonical_spell(
                        name="Magic Missile",
                        level=1,
                        start_line=1,
                        end_line=2,
                    ),
                )
            ],
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[
                        DiscoverySpellStart(start_line=1),
                        DiscoverySpellStart(start_line=2),
                    ],
                    active_heading="Wizard Spells",
                )
            ]
        )

        result = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=lambda _page_input: next(page_responses),
            session_state=existing_session,
        )
        validated_result = SessionState.model_validate(result.model_dump(mode="json"))

        self.assertEqual(len(validated_result.records), 2)
        self.assertEqual(
            [record.spell_id for record in validated_result.records],
            [existing_spell_id, f"pending-{SHA_DISCOVERY}-000002"],
        )
        self.assertEqual(
            validated_result.records[1].status,
            SpellRecordStatus.PENDING_EXTRACTION,
        )
        self.assertEqual(validated_result.records[1].boundary_start_line, 2)
        self.assertEqual(validated_result.records[1].boundary_end_line, 3)

    def test_detect_spells_skips_pending_duplicates_for_existing_non_pending_records_with_custom_ids(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Shield"]]
        )
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="confirmed-migrated-id",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=1,
                    boundary_end_line=2,
                    context_heading="Wizard Spells",
                    canonical_spell=_canonical_spell(
                        name="Magic Missile",
                        level=1,
                        start_line=1,
                        end_line=2,
                    ),
                )
            ],
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[
                        DiscoverySpellStart(start_line=1),
                        DiscoverySpellStart(start_line=2),
                    ],
                    active_heading="Wizard Spells",
                )
            ]
        )

        result = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=lambda _page_input: next(page_responses),
            session_state=existing_session,
        )

        self.assertEqual(
            [record.spell_id for record in result.records],
            ["confirmed-migrated-id", f"pending-{SHA_DISCOVERY}-000002"],
        )
        self.assertEqual(
            [record.boundary_start_line for record in result.records],
            [1, 2],
        )

    def test_detect_spells_skips_pending_duplicates_when_spell_id_already_exists(self) -> None:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Shield"]]
        )
        existing_spell_id = f"pending-{SHA_DISCOVERY}-000001"
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id=existing_spell_id,
                    status=SpellRecordStatus.NEEDS_REVIEW,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=0,
                    boundary_end_line=1,
                    context_heading="Wizard Spells",
                )
            ],
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[
                        DiscoverySpellStart(start_line=1),
                        DiscoverySpellStart(start_line=2),
                    ],
                    active_heading="Wizard Spells",
                )
            ]
        )

        result = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=lambda _page_input: next(page_responses),
            session_state=existing_session,
        )
        validated_result = SessionState.model_validate(result.model_dump(mode="json"))

        self.assertEqual(
            [record.spell_id for record in validated_result.records],
            [existing_spell_id, f"pending-{SHA_DISCOVERY}-000002"],
        )
        self.assertEqual(
            [record.boundary_start_line for record in validated_result.records],
            [0, 2],
        )

    def test_detect_spells_preserves_caller_session_state_when_discovery_fails(self) -> None:
        routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="pending-existing",
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=1,
                    boundary_end_line=2,
                    context_heading="Wizard Spells",
                )
            ],
        )
        original_snapshot = existing_session.model_dump(mode="json")

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            raise RuntimeError("stage1 failed")

        with self.assertRaisesRegex(RuntimeError, "stage1 failed"):
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_state=existing_session,
            )

        self.assertEqual(existing_session.model_dump(mode="json"), original_snapshot)

    def test_detect_spells_exposes_partial_pending_records_when_discovery_is_interrupted(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Shield", "Negates magic missile"],
                ["Lightning Bolt"],
            ]
        )
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="confirmed-existing",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=99,
                    boundary_end_line=120,
                    context_heading="Appendix",
                    canonical_spell=_canonical_spell(
                        name="Existing Spell",
                        level=2,
                        start_line=99,
                        end_line=120,
                    ),
                )
            ],
        )
        original_snapshot = existing_session.model_dump(mode="json")
        page_calls = 0

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal page_calls
            page_calls += 1
            if page_calls == 1:
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                )
            if page_calls == 2:
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                )
            raise RuntimeError("stage1 interrupted")

        with self.assertRaisesRegex(DiscoveryInterruptedError, "stage1 interrupted") as caught:
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_state=existing_session,
            )

        partial_session = caught.exception.partial_session_state
        self.assertEqual(existing_session.model_dump(mode="json"), original_snapshot)
        self.assertEqual(len(partial_session.records), 2)
        self.assertEqual(partial_session.records[0].spell_id, "confirmed-existing")
        self.assertEqual(
            partial_session.records[1].status,
            SpellRecordStatus.PENDING_EXTRACTION,
        )
        self.assertEqual(partial_session.records[1].boundary_start_line, 1)
        self.assertEqual(partial_session.records[1].boundary_end_line, 3)
        self.assertEqual(partial_session.records[1].context_heading, "Wizard Spells")

    def test_detect_spells_interruption_preserves_existing_pending_records_and_newly_closed_spans(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Shield", "Negates magic missile"],
                ["Lightning Bolt"],
            ]
        )
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="confirmed-existing",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=99,
                    boundary_end_line=120,
                    context_heading="Appendix",
                    canonical_spell=_canonical_spell(
                        name="Existing Spell",
                        level=2,
                        start_line=99,
                        end_line=120,
                    ),
                ),
                SpellRecord(
                    spell_id=f"pending-{SHA_DISCOVERY}-000003",
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=1,
                    section_order=1,
                    boundary_start_line=3,
                    boundary_end_line=5,
                    context_heading="Wizard Spells",
                ),
            ],
        )
        original_snapshot = existing_session.model_dump(mode="json")
        page_calls = 0

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal page_calls
            page_calls += 1
            if page_calls == 1:
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                )
            if page_calls == 2:
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                )
            raise RuntimeError("stage1 interrupted")

        with self.assertRaisesRegex(DiscoveryInterruptedError, "stage1 interrupted") as caught:
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_state=existing_session,
            )

        partial_session = caught.exception.partial_session_state
        self.assertEqual(existing_session.model_dump(mode="json"), original_snapshot)
        self.assertEqual(
            [record.spell_id for record in partial_session.records],
            [
                "confirmed-existing",
                f"pending-{SHA_DISCOVERY}-000003",
                f"pending-{SHA_DISCOVERY}-000001",
            ],
        )
        self.assertEqual(
            [record.status for record in partial_session.records],
            [
                SpellRecordStatus.CONFIRMED,
                SpellRecordStatus.PENDING_EXTRACTION,
                SpellRecordStatus.PENDING_EXTRACTION,
            ],
        )
        self.assertEqual(partial_session.records[1].boundary_start_line, 3)
        self.assertEqual(partial_session.records[1].boundary_end_line, 5)
        self.assertEqual(partial_session.records[2].boundary_start_line, 1)
        self.assertEqual(partial_session.records[2].boundary_end_line, 3)

    def test_detect_spells_wraps_in_loop_page_range_failures_with_partial_state(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Shield", "Negates magic missile"],
                ["Lightning Bolt"],
            ]
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=99)],
                    active_heading="Wizard Spells",
                ),
            ]
        )

        with self.assertRaisesRegex(DiscoveryInterruptedError, "outside page range") as caught:
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: next(page_responses),
            )

        partial_session = caught.exception.partial_session_state
        self.assertEqual(len(partial_session.records), 1)
        self.assertEqual(
            partial_session.records[0].status,
            SpellRecordStatus.PENDING_EXTRACTION,
        )
        self.assertEqual(partial_session.records[0].boundary_start_line, 1)
        self.assertEqual(partial_session.records[0].boundary_end_line, 3)
        self.assertEqual(partial_session.records[0].context_heading, "Wizard Spells")

    def test_detect_spells_interruption_from_in_loop_failure_preserves_pending_selection_and_new_spans(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Shield", "Negates magic missile"],
                ["Lightning Bolt"],
            ]
        )
        selected_pending_id = f"pending-{SHA_DISCOVERY}-000030"
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="confirmed-existing",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=99,
                    boundary_end_line=120,
                    context_heading="Appendix",
                    canonical_spell=_canonical_spell(
                        name="Existing Spell",
                        level=2,
                        start_line=99,
                        end_line=120,
                    ),
                ),
                SpellRecord(
                    spell_id=selected_pending_id,
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=1,
                    section_order=1,
                    boundary_start_line=30,
                    boundary_end_line=35,
                    context_heading="Wizard Spells",
                ),
            ],
            selected_spell_id=selected_pending_id,
        )
        original_snapshot = existing_session.model_dump(mode="json")
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=99)],
                    active_heading="Wizard Spells",
                ),
            ]
        )

        with self.assertRaisesRegex(DiscoveryInterruptedError, "outside page range") as caught:
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: next(page_responses),
                session_state=existing_session,
            )

        partial_session = caught.exception.partial_session_state
        self.assertEqual(existing_session.model_dump(mode="json"), original_snapshot)
        self.assertEqual(partial_session.selected_spell_id, selected_pending_id)
        self.assertEqual(
            [record.spell_id for record in partial_session.records],
            [
                "confirmed-existing",
                selected_pending_id,
                f"pending-{SHA_DISCOVERY}-000001",
            ],
        )

    def test_detect_spells_interruption_seeds_new_orders_from_original_session_order_space(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Shield", "Negates magic missile"],
                ["Lightning Bolt"],
            ]
        )
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="confirmed-existing",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=99,
                    boundary_end_line=120,
                    context_heading="Appendix",
                    canonical_spell=_canonical_spell(
                        name="Existing Spell",
                        level=2,
                        start_line=99,
                        end_line=120,
                    ),
                ),
                SpellRecord(
                    spell_id=f"pending-{SHA_DISCOVERY}-000030",
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=1,
                    section_order=1,
                    boundary_start_line=30,
                    boundary_end_line=35,
                    context_heading="Wizard Spells",
                ),
            ],
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=99)],
                    active_heading="Wizard Spells",
                ),
            ]
        )

        with self.assertRaisesRegex(DiscoveryInterruptedError, "outside page range") as caught:
            detect_spells(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: next(page_responses),
                session_state=existing_session,
            )

        partial_session = caught.exception.partial_session_state
        new_pending_record = next(
            record
            for record in partial_session.records
            if record.spell_id == f"pending-{SHA_DISCOVERY}-000001"
        )
        self.assertEqual(new_pending_record.extraction_order, 2)
        self.assertEqual(new_pending_record.section_order, 2)


class APIKeyResolutionTests(unittest.TestCase):
    def test_resolve_anthropic_api_key_uses_local_plaintext_before_keyring_when_configured(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                side_effect=AssertionError("keyring lookup should not run"),
            ):
                resolved = _resolve_anthropic_api_key(
                    AppConfig(
                        api_key_storage_mode="local_plaintext",
                        api_key=" plaintext-primary ",
                    )
                )

        self.assertEqual(resolved, "plaintext-primary")

    def test_resolve_anthropic_api_key_keeps_env_var_precedence_over_configured_mode(
        self,
    ) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": " env-primary "}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                side_effect=AssertionError("keyring lookup should not run"),
            ):
                resolved = _resolve_anthropic_api_key(
                    AppConfig(
                        api_key_storage_mode="credential_manager",
                        api_key=" plaintext-fallback ",
                    )
                )

        self.assertEqual(resolved, "env-primary")

    def test_resolve_anthropic_api_key_credential_manager_mode_does_not_fall_back_to_plaintext(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                side_effect=RuntimeError("backend unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "No Anthropic API key"):
                    _resolve_anthropic_api_key(
                        AppConfig(
                            api_key_storage_mode="credential_manager",
                            api_key=" plaintext-fallback ",
                        )
                    )

    def test_resolve_anthropic_api_key_uses_keyring_only_in_credential_manager_mode(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                return_value="keyring-primary",
            ):
                resolved = _resolve_anthropic_api_key(
                    AppConfig(
                        api_key_storage_mode="credential_manager",
                        api_key=" plaintext-fallback ",
                    )
                )

        self.assertEqual(resolved, "keyring-primary")

    def test_resolve_anthropic_api_key_local_plaintext_mode_does_not_fall_back_to_keyring(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                side_effect=AssertionError("keyring lookup should not run"),
            ):
                with self.assertRaisesRegex(RuntimeError, "No Anthropic API key"):
                    _resolve_anthropic_api_key(
                        AppConfig(
                            api_key_storage_mode="local_plaintext",
                            api_key="   ",
                        )
                    )

    def test_read_keyring_api_key_returns_empty_string_when_backend_lookup_raises(self) -> None:
        failing_keyring = SimpleNamespace(get_password=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("backend unavailable")))

        with patch("app.pipeline.extraction.import_module", return_value=failing_keyring):
            self.assertEqual(_read_keyring_api_key(), "")

    def test_resolve_anthropic_api_key_env_mode_does_not_fall_back_to_other_sources(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.pipeline.extraction._read_keyring_api_key",
                side_effect=AssertionError("keyring lookup should not run"),
            ):
                with self.assertRaisesRegex(RuntimeError, "No Anthropic API key"):
                    _resolve_anthropic_api_key(
                        AppConfig(
                            api_key_storage_mode="env",
                            api_key=" plaintext-fallback ",
                        )
                    )

    def test_detect_spells_carries_heading_forward_and_closes_cross_page_spans(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Damage: 1d4+1", "Shield", "Negates magic missile"],
            ]
        )
        page_inputs: list[DiscoveryPageInput] = []
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=4)],
                    active_heading="Wizard Spells",
                ),
            ]
        )

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(len(page_inputs), 2)
        self.assertIn("0: Wizard Spells", page_inputs[0].prompt)
        self.assertIn("3: Damage: 1d4+1", page_inputs[1].prompt)

        self.assertEqual(len(session_state.records), 2)

        first_record, second_record = session_state.records
        self.assertTrue(first_record.spell_id.startswith("pending-"))
        self.assertEqual(first_record.status, SpellRecordStatus.PENDING_EXTRACTION)
        self.assertEqual(first_record.boundary_start_line, 1)
        self.assertEqual(first_record.boundary_end_line, 4)
        self.assertEqual(first_record.context_heading, "Wizard Spells")
        self.assertIsNone(first_record.canonical_spell)

        self.assertTrue(second_record.spell_id.startswith("pending-"))
        self.assertEqual(second_record.status, SpellRecordStatus.PENDING_EXTRACTION)
        self.assertEqual(second_record.boundary_start_line, 4)
        self.assertEqual(second_record.boundary_end_line, 6)
        self.assertEqual(second_record.context_heading, "Wizard Spells")
        self.assertIsNone(second_record.draft_spell)

    def test_detect_spells_persists_heading_when_stage1_returns_null_active_heading(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                ["Damage: 1d4+1"],
                ["Shield", "Negates magic missile"],
            ]
        )
        page_inputs: list[DiscoveryPageInput] = []
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    active_heading=None,
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=4)],
                    active_heading=None,
                ),
            ]
        )

        def page_caller(page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            page_inputs.append(page_input)
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(len(page_inputs), 3)
        self.assertIn('"prior_active_heading": "Wizard Spells"', page_inputs[2].prompt)
        self.assertEqual(len(session_state.records), 2)
        first_record, second_record = session_state.records
        self.assertEqual(first_record.context_heading, "Wizard Spells")
        self.assertEqual(second_record.context_heading, "Wizard Spells")
        self.assertEqual(first_record.boundary_end_line, 4)
        self.assertEqual(second_record.boundary_start_line, 4)

    def test_detect_spells_stops_when_end_of_spells_section_is_reported(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Damage: 1d4+1"],
                ["Appendix"],
                ["Should not be scanned"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(),
                DiscoveryPageResponse(end_of_spells_section=True),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=5),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 1)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 3)

    def test_detect_spells_keeps_final_span_on_stop_page_when_page_also_has_spell_start(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Damage: 1d4+1", "Shield", "Appendix"],
                ["Should not be scanned"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading="Wizard Spells",
                    end_of_spells_section=True,
                ),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=5),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 2)
        self.assertEqual(len(session_state.records), 2)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 3)
        self.assertEqual(session_state.records[1].boundary_start_line, 3)
        self.assertEqual(session_state.records[1].boundary_end_line, 5)

    def test_detect_spells_does_not_absorb_mixed_stop_page_content_by_default(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Damage: 1d4+1", "Appendix"],
                ["Should not be scanned"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(
                    active_heading="Wizard Spells",
                    end_of_spells_section=True,
                ),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=5),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 2)
        self.assertEqual(len(session_state.records), 1)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 2)

    def test_detect_spells_stops_after_configured_empty_page_cutoff(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                [""],
                [""],
                ["Shield"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(),
                DiscoveryPageResponse(),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 1)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 2)

    def test_detect_spells_does_not_advance_empty_cutoff_for_continuation_pages_with_active_heading(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Damage: 1d4+1"],
                ["Shield"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(active_heading="Wizard Spells"),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                ),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=1),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 2)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 3)
        self.assertEqual(session_state.records[1].boundary_start_line, 3)
        self.assertEqual(session_state.records[1].boundary_end_line, 4)

    def test_detect_spells_does_not_advance_empty_cutoff_for_continuation_pages_with_carried_heading(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Damage: 1d4+1"],
                ["Shield"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(active_heading=None),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading=None,
                ),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=1),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 2)
        self.assertEqual(session_state.records[0].context_heading, "Wizard Spells")
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 3)
        self.assertEqual(session_state.records[1].context_heading, "Wizard Spells")
        self.assertEqual(session_state.records[1].boundary_start_line, 3)
        self.assertEqual(session_state.records[1].boundary_end_line, 4)

    def test_detect_spells_does_not_advance_empty_cutoff_for_short_non_blank_continuation_pages(
        self,
    ) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["Negates"],
                ["Shield"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(active_heading=None),
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=3)],
                    active_heading=None,
                ),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=1),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 2)
        self.assertEqual(session_state.records[0].context_heading, "Wizard Spells")
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 3)
        self.assertEqual(session_state.records[1].context_heading, "Wizard Spells")
        self.assertEqual(session_state.records[1].boundary_start_line, 3)
        self.assertEqual(session_state.records[1].boundary_end_line, 4)

    def test_detect_spells_counts_whitespace_only_pages_toward_empty_cutoff(self) -> None:
        routed_document = _build_routed_document(
            [
                ["Wizard Spells", "Magic Missile"],
                ["   "],
                ["\t"],
                ["Shield"],
            ]
        )
        call_count = 0
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                ),
                DiscoveryPageResponse(),
                DiscoveryPageResponse(),
            ]
        )

        def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
            nonlocal call_count
            call_count += 1
            return next(page_responses)

        session_state = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=page_caller,
        )

        self.assertEqual(call_count, 3)
        self.assertEqual(len(session_state.records), 1)
        self.assertEqual(session_state.records[0].boundary_start_line, 1)
        self.assertEqual(session_state.records[0].boundary_end_line, 2)

    def test_detect_spells_seeds_new_orders_from_existing_order_values(self) -> None:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Shield"]]
        )
        existing_session = SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id=f"pending-{SHA_DISCOVERY}-000001",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=4,
                    section_order=7,
                    boundary_start_line=1,
                    boundary_end_line=2,
                    context_heading="Wizard Spells",
                    canonical_spell=_canonical_spell(
                        name="Magic Missile",
                        level=1,
                        start_line=1,
                        end_line=2,
                    ),
                )
            ],
        )
        page_responses = iter(
            [
                DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=2)],
                    active_heading="Wizard Spells",
                )
            ]
        )

        result = detect_spells(
            routed_document,
            config=AppConfig(stage1_empty_page_cutoff=2),
            page_caller=lambda _page_input: next(page_responses),
            session_state=existing_session,
        )

        self.assertEqual(len(result.records), 2)
        pending_record = result.records[1]
        self.assertEqual(pending_record.status, SpellRecordStatus.PENDING_EXTRACTION)
        self.assertGreater(pending_record.extraction_order, result.records[0].extraction_order)
        self.assertGreater(pending_record.section_order, result.records[0].section_order)


class DiscoveryPersistenceHelperTests(unittest.TestCase):
    def test_restore_discovery_session_uses_routed_document_hash_and_refreshes_document_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
            moved_document = replace(
                routed_document,
                source_path=Path(r"C:\\tmp\\moved-spellbook.pdf"),
            )
            stale_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=r"C:\\tmp\\old-spellbook.pdf",
                coordinate_map=CoordinateAwareTextMap(
                    lines=[
                        (
                            "Wizard Spells",
                            TextRegion(page=9, bbox=(0.0, 0.0, 1.0, 1.0)),
                        ),
                        (
                            "Magic Missile",
                            TextRegion(page=9, bbox=(0.0, 1.0, 1.0, 2.0)),
                        ),
                    ]
                ),
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(stale_session, session_path=session_path)

            restored = restore_discovery_session(
                moved_document,
                session_path=session_path,
            )

            self.assertIsNotNone(restored)
            if restored is None:
                self.fail("Expected matching source hash to restore a discovery session.")
            self.assertEqual(restored.last_open_path, str(moved_document.source_path))
            self.assertEqual(
                restored.coordinate_map.model_dump(mode="json"),
                moved_document.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(len(restored.records), 1)
            self.assertEqual(restored.records[0].boundary_start_line, 1)

    def test_restore_discovery_session_restores_same_hash_session_when_line_mapping_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_document = _build_routed_document([[['Wizard Spells', 'Magic Missile']][0]])
            rerouted_document = _build_routed_document([[['Wizard Spells Magic', 'Missile']][0]])
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(original_document.source_path),
                coordinate_map=original_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
                selected_spell_id=f"pending-{SHA_DISCOVERY}-000001",
            )
            save_session_state(saved_session, session_path=session_path)

            restored = restore_discovery_session(
                rerouted_document,
                session_path=session_path,
            )

            self.assertIsNotNone(restored)
            if restored is None:
                self.fail("Expected matching source hash to restore even when line mapping changes.")
            self.assertEqual(restored.last_open_path, str(rerouted_document.source_path))
            self.assertEqual(restored.selected_spell_id, saved_session.selected_spell_id)
            self.assertEqual(
                restored.coordinate_map.model_dump(mode="json"),
                rerouted_document.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(len(restored.records), 1)
            self.assertEqual(restored.records[0].spell_id, f"pending-{SHA_DISCOVERY}-000001")

    def test_restore_discovery_session_normalizes_restored_boundaries_to_current_line_count(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            stale_coordinate_map = CoordinateAwareTextMap(
                lines=[
                    (
                        f"line {line_index}",
                        TextRegion(
                            page=0,
                            bbox=(0.0, float(line_index), 1.0, float(line_index + 1)),
                        ),
                    )
                    for line_index in range(200)
                ]
            )
            rerouted_document = _build_routed_document([["Only one line"]])
            stale_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=r"C:\\tmp\\old-spellbook.pdf",
                coordinate_map=stale_coordinate_map,
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000150",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=150,
                        boundary_end_line=180,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(stale_session, session_path=session_path)

            restored = restore_discovery_session(
                rerouted_document,
                session_path=session_path,
            )

            self.assertIsNotNone(restored)
            if restored is None:
                self.fail("Expected matching source hash to restore and normalize boundaries.")
            self.assertEqual(restored.records[0].boundary_start_line, 0)
            self.assertEqual(restored.records[0].boundary_end_line, 1)
            self.assertEqual(
                len(
                    restored.coordinate_map.regions_for_range(
                        restored.records[0].boundary_start_line,
                        restored.records[0].boundary_end_line,
                    )
                ),
                1,
            )

    def test_open_or_restore_discovery_session_keeps_saved_coordinate_map_when_rerouted_document_has_no_lines(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_document = _build_routed_document(
                [["Wizard Spells", "Magic Missile", "Shield"]]
            )
            empty_document = replace(
                original_document,
                source_path=Path(r"C:\\tmp\\empty-spellbook.pdf"),
                markdown_text="",
                coordinate_map=CoordinateAwareTextMap(lines=[]),
                default_source_pages=[],
            )
            selected_pending_id = f"pending-{SHA_DISCOVERY}-000002"
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(original_document.source_path),
                coordinate_map=original_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id="confirmed-existing",
                        status=SpellRecordStatus.CONFIRMED,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                        canonical_spell=_canonical_spell(
                            name="Magic Missile",
                            level=1,
                            start_line=1,
                            end_line=2,
                        ),
                    ),
                    SpellRecord(
                        spell_id=selected_pending_id,
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=1,
                        section_order=1,
                        boundary_start_line=2,
                        boundary_end_line=3,
                        context_heading="Wizard Spells",
                    ),
                ],
                selected_spell_id=selected_pending_id,
            )
            save_session_state(saved_session, session_path=session_path)

            reopened = open_or_restore_discovery_session(
                empty_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: (_ for _ in ()).throw(
                    AssertionError("page_caller should not run when same-hash pending records restore")
                ),
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected reopen helper to persist the restored zero-line session.")

            self.assertEqual(reopened.last_open_path, str(empty_document.source_path))
            self.assertEqual(
                reopened.coordinate_map.model_dump(mode="json"),
                saved_session.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(reopened.selected_spell_id, selected_pending_id)
            self.assertEqual(
                len(
                    reopened.coordinate_map.regions_for_range(
                        reopened.records[1].boundary_start_line,
                        reopened.records[1].boundary_end_line,
                    )
                ),
                1,
            )
            self.assertEqual(
                reopened.model_dump(mode="json"),
                {
                    **saved_session.model_copy(
                        update={
                            "last_open_path": str(empty_document.source_path),
                        },
                        deep=True,
                    ).model_dump(mode="json")
                },
            )
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                reopened.model_dump(mode="json"),
            )
            self.assertEqual(
                len(
                    saved_state.coordinate_map.regions_for_range(
                        saved_state.records[1].boundary_start_line,
                        saved_state.records[1].boundary_end_line,
                    )
                ),
                1,
            )

    def test_open_or_restore_discovery_session_restores_compatible_pending_session_without_rerunning_stage1(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
            moved_document = replace(
                routed_document,
                source_path=Path(r"C:\\tmp\\moved-spellbook.pdf"),
            )
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=r"C:\\tmp\\old-spellbook.pdf",
                coordinate_map=routed_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(saved_session, session_path=session_path)

            restored = open_or_restore_discovery_session(
                moved_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: (_ for _ in ()).throw(
                    AssertionError("page_caller should not run when pending records restore")
                ),
                session_path=session_path,
            )

            self.assertEqual(restored.last_open_path, str(moved_document.source_path))
            self.assertEqual(
                restored.coordinate_map.model_dump(mode="json"),
                moved_document.coordinate_map.model_dump(mode="json"),
            )
            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected reopened restored session to persist refreshed context.")
            self.assertEqual(saved_state.last_open_path, str(moved_document.source_path))
            self.assertEqual(
                saved_state.coordinate_map.model_dump(mode="json"),
                moved_document.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(len(restored.records), 1)
            self.assertEqual(restored.records[0].status, SpellRecordStatus.PENDING_EXTRACTION)
            self.assertEqual(restored.records[0].boundary_start_line, 1)
            self.assertEqual(restored.records[0].boundary_end_line, 2)

    def test_open_or_restore_discovery_session_persists_restored_context_at_default_session_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {"APPDATA": tmp_dir},
            clear=False,
        ):
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
            moved_document = replace(
                routed_document,
                source_path=Path(r"C:\\tmp\\moved-spellbook.pdf"),
            )
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=r"C:\\tmp\\old-spellbook.pdf",
                coordinate_map=CoordinateAwareTextMap(
                    lines=[
                        (
                            "Wizard Spells",
                            TextRegion(page=9, bbox=(0.0, 0.0, 1.0, 1.0)),
                        ),
                        (
                            "Magic Missile",
                            TextRegion(page=9, bbox=(0.0, 1.0, 1.0, 2.0)),
                        ),
                    ]
                ),
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(saved_session)

            restored = open_or_restore_discovery_session(
                moved_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: (_ for _ in ()).throw(
                    AssertionError("page_caller should not run when pending records restore")
                ),
            )

            saved_state = load_session_state()
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected default session path reopen to persist refreshed context.")
            self.assertEqual(restored.last_open_path, str(moved_document.source_path))
            self.assertEqual(saved_state.last_open_path, str(moved_document.source_path))
            self.assertEqual(
                saved_state.coordinate_map.model_dump(mode="json"),
                moved_document.coordinate_map.model_dump(mode="json"),
            )

    def test_open_or_restore_discovery_session_reruns_stage1_when_restored_session_has_no_pending_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile", "Shield"]])
            restored_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(routed_document.source_path),
                coordinate_map=routed_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id="confirmed-existing",
                        status=SpellRecordStatus.CONFIRMED,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                        canonical_spell=_canonical_spell(
                            name="Magic Missile",
                            level=1,
                            start_line=1,
                            end_line=2,
                        ),
                    )
                ],
            )
            save_session_state(restored_session, session_path=session_path)

            page_call_count = 0

            def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
                nonlocal page_call_count
                page_call_count += 1
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=2)],
                    active_heading="Wizard Spells",
                )

            reopened = open_or_restore_discovery_session(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected reopen helper to persist the restored session.")

            self.assertEqual(page_call_count, 1)
            self.assertEqual(len(reopened.records), 2)
            self.assertEqual(
                [record.spell_id for record in reopened.records],
                [
                    "confirmed-existing",
                    f"pending-{SHA_DISCOVERY}-000002",
                ],
            )
            self.assertEqual(reopened.records[1].status, SpellRecordStatus.PENDING_EXTRACTION)
            self.assertEqual(reopened.records[1].boundary_start_line, 2)
            self.assertEqual(reopened.records[1].boundary_end_line, 3)
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                reopened.model_dump(mode="json"),
            )

    def test_open_or_restore_discovery_session_restores_same_hash_session_without_rerunning_stage1_when_line_mapping_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_document = _build_routed_document(
                [["Wizard Spells", "Magic Missile", "Shield", "Feather Fall"]]
            )
            rerouted_document = _build_routed_document(
                [["Wizard Spells Magic Missile", "Shield", "Feather Fall", "Range: 10 yards"]]
            )
            selected_pending_id = f"pending-{SHA_DISCOVERY}-000003"
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(original_document.source_path),
                coordinate_map=original_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id="confirmed-existing",
                        status=SpellRecordStatus.CONFIRMED,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                        canonical_spell=_canonical_spell(
                            name="Magic Missile",
                            level=1,
                            start_line=1,
                            end_line=2,
                        ),
                    ),
                    SpellRecord(
                        spell_id="needs-review-existing",
                        status=SpellRecordStatus.NEEDS_REVIEW,
                        extraction_order=1,
                        section_order=1,
                        boundary_start_line=2,
                        boundary_end_line=3,
                        context_heading="Wizard Spells",
                        draft_spell=_canonical_spell(
                            name="Shield",
                            level=1,
                            start_line=2,
                            end_line=3,
                        ),
                    ),
                    SpellRecord(
                        spell_id=selected_pending_id,
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=2,
                        section_order=2,
                        boundary_start_line=3,
                        boundary_end_line=4,
                        context_heading="Wizard Spells",
                    ),
                ],
                selected_spell_id=selected_pending_id,
            )
            save_session_state(saved_session, session_path=session_path)

            reopened = open_or_restore_discovery_session(
                rerouted_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: (_ for _ in ()).throw(
                    AssertionError("page_caller should not run when same-hash sessions restore")
                ),
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected reopen helper to persist the restored session.")

            expected_session = saved_session.model_copy(deep=True)
            expected_session.last_open_path = str(rerouted_document.source_path)
            expected_session.coordinate_map = rerouted_document.coordinate_map

            self.assertEqual(
                reopened.model_dump(mode="json"),
                expected_session.model_dump(mode="json"),
            )
            self.assertEqual(reopened.selected_spell_id, selected_pending_id)
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                reopened.model_dump(mode="json"),
            )

    def test_open_or_restore_discovery_session_falls_back_to_fresh_discovery_for_sessions_with_different_source_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
            rerouted_document = _build_routed_document(
                [["Wizard Spells", "Shield", "Range: Self"]]
            )
            stale_session = SessionState(
                source_sha256_hex="b" * 64,
                last_open_path=str(original_document.source_path),
                coordinate_map=original_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(stale_session, session_path=session_path)

            page_call_count = 0

            def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
                nonlocal page_call_count
                page_call_count += 1
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=1)],
                    active_heading="Wizard Spells",
                )

            discovered = open_or_restore_discovery_session(
                rerouted_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected reopen helper to autosave the fresh discovery session.")

            self.assertEqual(page_call_count, 1)
            self.assertEqual(len(discovered.records), 1)
            self.assertEqual(discovered.records[0].status, SpellRecordStatus.PENDING_EXTRACTION)
            self.assertEqual(discovered.records[0].boundary_start_line, 1)
            self.assertEqual(discovered.records[0].boundary_end_line, 3)
            self.assertEqual(
                discovered.coordinate_map.model_dump(mode="json"),
                rerouted_document.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                discovered.model_dump(mode="json"),
            )

    def test_detect_spells_with_autosave_persists_completed_discovery_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile"]])
            page_responses = iter(
                [
                    DiscoveryPageResponse(
                        spell_starts=[DiscoverySpellStart(start_line=1)],
                        active_heading="Wizard Spells",
                    )
                ]
            )

            session_state = detect_spells_with_autosave(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: next(page_responses),
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected autosave helper to persist the completed discovery session.")
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                session_state.model_dump(mode="json"),
            )
            self.assertEqual(len(saved_state.records), 1)
            self.assertEqual(saved_state.records[0].boundary_start_line, 1)
            self.assertEqual(saved_state.records[0].boundary_end_line, 2)

    def test_detect_spells_with_autosave_restores_saved_session_without_rerunning_stage1(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile", "Shield"]])
            stale_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=r"C:\\tmp\\old-spellbook.pdf",
                coordinate_map=routed_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id=f"pending-{SHA_DISCOVERY}-000001",
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                    )
                ],
            )
            save_session_state(stale_session, session_path=session_path)

            page_call_count = 0

            def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
                nonlocal page_call_count
                page_call_count += 1
                raise AssertionError("page_caller should not run when a compatible session restores")

            restored = detect_spells_with_autosave(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected autosave helper to persist the rerun discovery session.")

            self.assertEqual(page_call_count, 0)
            self.assertEqual(restored.last_open_path, str(routed_document.source_path))
            self.assertEqual(
                restored.coordinate_map.model_dump(mode="json"),
                routed_document.coordinate_map.model_dump(mode="json"),
            )
            self.assertEqual(len(restored.records), 1)
            self.assertEqual(restored.records[0].spell_id, f"pending-{SHA_DISCOVERY}-000001")
            self.assertEqual(restored.records[0].boundary_start_line, 1)
            self.assertEqual(restored.records[0].boundary_end_line, 2)
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                restored.model_dump(mode="json"),
            )

    def test_detect_spells_with_autosave_reruns_stage1_when_restored_session_has_no_pending_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document([["Wizard Spells", "Magic Missile", "Shield"]])
            restored_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(routed_document.source_path),
                coordinate_map=routed_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id="confirmed-existing",
                        status=SpellRecordStatus.CONFIRMED,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                        canonical_spell=_canonical_spell(
                            name="Magic Missile",
                            level=1,
                            start_line=1,
                            end_line=2,
                        ),
                    )
                ],
            )
            save_session_state(restored_session, session_path=session_path)

            page_call_count = 0

            def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
                nonlocal page_call_count
                page_call_count += 1
                return DiscoveryPageResponse(
                    spell_starts=[DiscoverySpellStart(start_line=2)],
                    active_heading="Wizard Spells",
                )

            discovered = detect_spells_with_autosave(
                routed_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=page_caller,
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected autosave helper to persist the rerun discovery session.")

            self.assertEqual(page_call_count, 1)
            self.assertEqual(
                [record.spell_id for record in discovered.records],
                [
                    "confirmed-existing",
                    f"pending-{SHA_DISCOVERY}-000002",
                ],
            )
            self.assertEqual(discovered.records[1].status, SpellRecordStatus.PENDING_EXTRACTION)
            self.assertEqual(discovered.records[1].boundary_start_line, 2)
            self.assertEqual(discovered.records[1].boundary_end_line, 3)
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                discovered.model_dump(mode="json"),
            )

    def test_detect_spells_with_autosave_restores_same_hash_session_without_rerunning_stage1_when_line_mapping_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            original_document = _build_routed_document(
                [["Wizard Spells", "Magic Missile", "Shield", "Feather Fall"]]
            )
            rerouted_document = _build_routed_document(
                [["Wizard Spells Magic Missile", "Shield", "Feather Fall", "Range: 10 yards"]]
            )
            selected_pending_id = f"pending-{SHA_DISCOVERY}-000003"
            saved_session = SessionState(
                source_sha256_hex=SHA_DISCOVERY,
                last_open_path=str(original_document.source_path),
                coordinate_map=original_document.coordinate_map,
                records=[
                    SpellRecord(
                        spell_id="confirmed-existing",
                        status=SpellRecordStatus.CONFIRMED,
                        extraction_order=0,
                        section_order=0,
                        boundary_start_line=1,
                        boundary_end_line=2,
                        context_heading="Wizard Spells",
                        canonical_spell=_canonical_spell(
                            name="Magic Missile",
                            level=1,
                            start_line=1,
                            end_line=2,
                        ),
                    ),
                    SpellRecord(
                        spell_id="needs-review-existing",
                        status=SpellRecordStatus.NEEDS_REVIEW,
                        extraction_order=1,
                        section_order=1,
                        boundary_start_line=2,
                        boundary_end_line=3,
                        context_heading="Wizard Spells",
                        draft_spell=_canonical_spell(
                            name="Shield",
                            level=1,
                            start_line=2,
                            end_line=3,
                        ),
                    ),
                    SpellRecord(
                        spell_id=selected_pending_id,
                        status=SpellRecordStatus.PENDING_EXTRACTION,
                        extraction_order=2,
                        section_order=2,
                        boundary_start_line=3,
                        boundary_end_line=4,
                        context_heading="Wizard Spells",
                    ),
                ],
                selected_spell_id=selected_pending_id,
            )
            save_session_state(saved_session, session_path=session_path)

            restored = detect_spells_with_autosave(
                rerouted_document,
                config=AppConfig(stage1_empty_page_cutoff=2),
                page_caller=lambda _page_input: (_ for _ in ()).throw(
                    AssertionError("page_caller should not run when same-hash sessions restore")
                ),
                session_path=session_path,
            )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected autosave helper to persist the restored session.")

            expected_session = saved_session.model_copy(deep=True)
            expected_session.last_open_path = str(rerouted_document.source_path)
            expected_session.coordinate_map = rerouted_document.coordinate_map

            self.assertEqual(
                restored.model_dump(mode="json"),
                expected_session.model_dump(mode="json"),
            )
            self.assertEqual(restored.selected_spell_id, selected_pending_id)
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                restored.model_dump(mode="json"),
            )

    def test_detect_spells_with_autosave_persists_partial_session_on_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.json"
            routed_document = _build_routed_document(
                [
                    ["Wizard Spells", "Magic Missile", "Range: 60 yards"],
                    ["Shield", "Negates magic missile"],
                    ["Lightning Bolt"],
                ]
            )
            page_calls = 0

            def page_caller(_page_input: DiscoveryPageInput) -> DiscoveryPageResponse:
                nonlocal page_calls
                page_calls += 1
                if page_calls == 1:
                    return DiscoveryPageResponse(
                        spell_starts=[DiscoverySpellStart(start_line=1)],
                        active_heading="Wizard Spells",
                    )
                if page_calls == 2:
                    return DiscoveryPageResponse(
                        spell_starts=[DiscoverySpellStart(start_line=3)],
                        active_heading="Wizard Spells",
                    )
                raise RuntimeError("stage1 interrupted")

            with self.assertRaisesRegex(DiscoveryInterruptedError, "stage1 interrupted") as caught:
                detect_spells_with_autosave(
                    routed_document,
                    config=AppConfig(stage1_empty_page_cutoff=2),
                    page_caller=page_caller,
                    session_path=session_path,
                )

            saved_state = load_session_state(session_path=session_path)
            self.assertIsNotNone(saved_state)
            if saved_state is None:
                self.fail("Expected autosave helper to persist the partial discovery session.")
            self.assertEqual(
                saved_state.model_dump(mode="json"),
                caught.exception.partial_session_state.model_dump(mode="json"),
            )
            self.assertEqual(len(saved_state.records), 1)
            self.assertEqual(saved_state.records[0].boundary_start_line, 1)
            self.assertEqual(saved_state.records[0].boundary_end_line, 3)


class Stage2ExtractionTests(unittest.TestCase):
    def _build_pending_session(self) -> SessionState:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Shield", "Range: 60 yards"]]
        )
        first_pending_id = f"pending-{SHA_DISCOVERY}-000001"
        second_pending_id = f"pending-{SHA_DISCOVERY}-000002"
        return SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id=first_pending_id,
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=1,
                    boundary_end_line=2,
                    context_heading="Wizard Spells",
                ),
                SpellRecord(
                    spell_id=second_pending_id,
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=1,
                    section_order=1,
                    boundary_start_line=2,
                    boundary_end_line=4,
                    context_heading="Wizard Spells",
                ),
            ],
            selected_spell_id=first_pending_id,
        )

    def test_extract_selected_pending_processes_only_selected_record(self) -> None:
        session_state = self._build_pending_session()
        selected_record = session_state.records[0]
        call_spell_ids: list[str] = []

        def stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            call_spell_ids.append(_request.record.spell_id)
            return _spell_payload(
                name="Magic Missile",
                level=1,
                start_line=_request.record.boundary_start_line,
                end_line=_request.record.boundary_end_line,
            )

        extract_selected_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=stage2_caller,
        )

        self.assertIs(session_state.records[0], selected_record)
        self.assertEqual(call_spell_ids, [selected_record.spell_id])
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.CONFIRMED)
        self.assertEqual(
            session_state.records[1].status,
            SpellRecordStatus.PENDING_EXTRACTION,
        )

    def test_extract_selected_pending_uses_default_stage2_caller_when_not_injected(self) -> None:
        session_state = self._build_pending_session()
        captured_requests: list[dict[str, object]] = []
        fake_message = SimpleNamespace(
            content=[
                {
                    "text": """{
                        "name": "Magic Missile",
                        "class_list": "Wizard",
                        "level": 1,
                        "school": ["Evocation"],
                        "range": "60 yards",
                        "components": ["V", "S"],
                        "duration": "1 round",
                        "casting_time": "1",
                        "area_of_effect": "1 creature",
                        "saving_throw": "None",
                        "description": "A missile of magical energy.",
                        "source_document": "Player's Handbook",
                        "source_page": 112,
                        "confidence": 0.95,
                        "needs_review": false,
                        "extraction_start_line": 1,
                        "extraction_end_line": 2
                    }"""
                }
            ]
        )
        fake_client = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **kwargs: captured_requests.append(kwargs) or fake_message
            )
        )
        fake_anthropic_module = SimpleNamespace(Anthropic=lambda api_key: fake_client)

        with patch(
            "app.pipeline.extraction._load_optional_module",
            return_value=fake_anthropic_module,
        ), patch(
            "app.pipeline.extraction._resolve_anthropic_api_key",
            return_value="test-key",
        ):
            extract_selected_pending(
                session_state,
                config=AppConfig(stage2_max_attempts=1),
            )

        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(request["model"], "claude-sonnet-4-latest")
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.CONFIRMED)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        if session_state.records[0].canonical_spell is None:
            self.fail("Expected selected record to be extracted through the default Stage 2 caller.")
        self.assertEqual(session_state.records[0].canonical_spell.name, "Magic Missile")
        self.assertEqual(
            session_state.records[1].status,
            SpellRecordStatus.PENDING_EXTRACTION,
        )

    def test_extract_all_pending_processes_remaining_pending_records(self) -> None:
        session_state = self._build_pending_session()
        call_spell_ids: list[str] = []

        def stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            call_spell_ids.append(_request.record.spell_id)
            return _spell_payload(
                name=f"Spell {_request.record.boundary_start_line}",
                level=1,
                start_line=_request.record.boundary_start_line,
                end_line=_request.record.boundary_end_line,
            )

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=stage2_caller,
        )

        self.assertEqual(len(call_spell_ids), 2)
        self.assertEqual(call_spell_ids, [record.spell_id for record in session_state.records])
        self.assertEqual(
            [record.status for record in session_state.records],
            [SpellRecordStatus.CONFIRMED, SpellRecordStatus.CONFIRMED],
        )

    def test_extract_all_pending_uses_default_stage2_caller_when_not_injected(self) -> None:
        session_state = self._build_pending_session()
        captured_requests: list[dict[str, object]] = []
        response_payloads = iter(
            [
                {
                    "name": "Magic Missile",
                    "class_list": "Wizard",
                    "level": 1,
                    "school": ["Evocation"],
                    "range": "60 yards",
                    "components": ["V", "S"],
                    "duration": "1 round",
                    "casting_time": "1",
                    "area_of_effect": "1 creature",
                    "saving_throw": "None",
                    "description": "First extracted spell.",
                    "source_document": "Player's Handbook",
                    "source_page": 112,
                    "confidence": 0.95,
                    "needs_review": False,
                    "extraction_start_line": 1,
                    "extraction_end_line": 2,
                },
                {
                    "name": "Shield",
                    "class_list": "Wizard",
                    "level": 1,
                    "school": ["Abjuration"],
                    "range": "Self",
                    "components": ["V", "S"],
                    "duration": "1 round",
                    "casting_time": "1",
                    "area_of_effect": "Special",
                    "saving_throw": "None",
                    "description": "Second extracted spell.",
                    "source_document": "Player's Handbook",
                    "source_page": 112,
                    "confidence": 0.95,
                    "needs_review": False,
                    "extraction_start_line": 2,
                    "extraction_end_line": 4,
                },
            ]
        )

        def _fake_create(**kwargs: object) -> SimpleNamespace:
            captured_requests.append(dict(kwargs))
            payload = next(response_payloads)
            return SimpleNamespace(
                content=[{"text": f"```json\n{json.dumps(payload)}\n```"}]
            )

        fake_client = SimpleNamespace(messages=SimpleNamespace(create=_fake_create))
        fake_anthropic_module = SimpleNamespace(Anthropic=lambda api_key: fake_client)

        with patch(
            "app.pipeline.extraction._load_optional_module",
            return_value=fake_anthropic_module,
        ), patch(
            "app.pipeline.extraction._resolve_anthropic_api_key",
            return_value="test-key",
        ):
            extract_all_pending(
                session_state,
                config=AppConfig(stage2_max_attempts=1),
            )

        self.assertEqual(len(captured_requests), 2)
        self.assertEqual(
            [request["model"] for request in captured_requests],
            ["claude-sonnet-4-latest", "claude-sonnet-4-latest"],
        )
        self.assertEqual(
            [record.status for record in session_state.records],
            [SpellRecordStatus.CONFIRMED, SpellRecordStatus.CONFIRMED],
        )
        self.assertEqual(
            [record.canonical_spell.name if record.canonical_spell else None for record in session_state.records],
            ["Magic Missile", "Shield"],
        )

    def test_extract_all_pending_sets_needs_review_for_weak_extraction(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id

        def weak_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            return {
                "name": "Broken Priest Spell",
                "class_list": "Priest",
                "level": "0",
                "school": [],
                "sphere": [],
                "source_document": "Player's Handbook",
                "extraction_start_line": _request.record.boundary_start_line,
                "extraction_end_line": _request.record.boundary_end_line,
            }

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=weak_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        self.assertTrue(session_state.records[0].canonical_spell.needs_review)

    def test_extract_all_pending_sets_confirmed_for_clean_extraction(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id

        def clean_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            return {
                **_spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=_request.record.boundary_start_line,
                    end_line=_request.record.boundary_end_line,
                ),
                "confidence": 0.95,
                "needs_review": False,
            }

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=clean_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.CONFIRMED)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        self.assertFalse(session_state.records[0].canonical_spell.needs_review)

    def test_extract_all_pending_overrides_model_provenance_with_record_boundaries(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        record = session_state.records[0]

        def stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            return {
                **_spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=999,
                    end_line=1000,
                ),
                "source_document": "hallucinated-source.pdf",
                "source_page": 999,
                "extraction_start_line": 999,
                "extraction_end_line": 1000,
            }

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=stage2_caller,
        )

        self.assertIsNotNone(record.canonical_spell)
        canonical_spell = record.canonical_spell
        if canonical_spell is None:
            self.fail("Expected extracted canonical spell.")
        self.assertEqual(canonical_spell.description, "Magic Missile description.")
        self.assertEqual(canonical_spell.source_document, "spellbook.pdf")
        self.assertEqual(canonical_spell.source_page, 0)
        self.assertEqual(canonical_spell.extraction_start_line, record.boundary_start_line)
        self.assertEqual(canonical_spell.extraction_end_line, record.boundary_end_line)

    def test_extract_all_pending_sets_needs_review_when_confidence_below_threshold(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id

        def low_confidence_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            return {
                **_spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=_request.record.boundary_start_line,
                    end_line=_request.record.boundary_end_line,
                ),
                "confidence": 0.7,
                "needs_review": False,
            }

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2, confidence_threshold=0.85),
            stage2_caller=low_confidence_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        self.assertFalse(session_state.records[0].canonical_spell.needs_review)

    def test_extract_all_pending_creates_placeholder_when_stage2_retries_exhausted(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        attempts = 0

        def failing_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("stage2 transport error")

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=3),
            stage2_caller=failing_stage2_caller,
        )

        self.assertEqual(attempts, 3)
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        self.assertTrue(session_state.records[0].canonical_spell.needs_review)
        self.assertIn(
            "failed after 3 attempt(s)",
            session_state.records[0].canonical_spell.review_notes or "",
        )

    def test_extract_all_pending_creates_placeholder_when_stage2_payload_is_malformed(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        attempts = 0

        def malformed_stage2_caller(_request: Stage2ExtractionInput) -> str:
            nonlocal attempts
            attempts += 1
            return "not a valid stage2 payload"

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=malformed_stage2_caller,
        )

        self.assertEqual(attempts, 2)
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell after malformed Stage 2 payload retries.")
        self.assertTrue(placeholder_spell.needs_review)
        self.assertIn("Stage 2 extraction failed", placeholder_spell.review_notes or "")
        self.assertIn("failed after 2 attempt(s)", placeholder_spell.review_notes or "")

    def test_extract_all_pending_creates_placeholder_when_stage2_payload_fails_schema_validation(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        attempts = 0

        def invalid_schema_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            nonlocal attempts
            attempts += 1
            return {
                "name": "Schema Failure Spell",
                "class_list": "Wizard",
                "level": "not-an-int",
                "school": [],
                "components": {"verbal": "yes"},
            }

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=invalid_schema_stage2_caller,
        )

        self.assertEqual(attempts, 2)
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell after invalid Stage 2 schema retries.")
        self.assertTrue(placeholder_spell.needs_review)
        self.assertIn("Stage 2 extraction failed", placeholder_spell.review_notes or "")
        self.assertIn("failed after 2 attempt(s)", placeholder_spell.review_notes or "")

    def test_extract_all_pending_placeholder_clamps_stale_boundaries_for_source_page(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        session_state.records[0].boundary_start_line = 999
        session_state.records[0].boundary_end_line = 1005

        def failing_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            raise RuntimeError("stage2 transport error")

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=1),
            stage2_caller=failing_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell after retries are exhausted.")
        self.assertTrue(placeholder_spell.needs_review)
        self.assertEqual(placeholder_spell.source_page, 0)
        self.assertIn("failed after 1 attempt(s)", placeholder_spell.review_notes or "")

    def test_extract_all_pending_placeholder_survives_page_span_value_error(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id

        def failing_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            raise RuntimeError("stage2 transport error")

        with patch(
            "app.pipeline.extraction.CoordinateAwareTextMap.page_span",
            side_effect=ValueError("stale boundary span"),
        ):
            extract_all_pending(
                session_state,
                config=AppConfig(stage2_max_attempts=1),
                stage2_caller=failing_stage2_caller,
            )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertIsNotNone(session_state.records[0].canonical_spell)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell when Stage 2 retries are exhausted.")
        self.assertTrue(placeholder_spell.needs_review)
        self.assertIsNone(placeholder_spell.source_page)
        self.assertIn("failed after 1 attempt(s)", placeholder_spell.review_notes or "")

    def test_extract_all_pending_placeholder_infers_priest_from_context_heading(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        session_state.records[0].context_heading = "Priest Spells"

        def failing_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            raise RuntimeError("stage2 transport error")

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=1),
            stage2_caller=failing_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell after retries are exhausted.")
        self.assertEqual(placeholder_spell.class_list, ClassList.PRIEST)
        self.assertEqual(placeholder_spell.level, 1)
        self.assertEqual(placeholder_spell.sphere, ["Unknown"])

    def test_extract_all_pending_placeholder_falls_back_to_wizard_when_heading_unknown(self) -> None:
        session_state = self._build_pending_session()
        session_state.records = [session_state.records[0]]
        session_state.selected_spell_id = session_state.records[0].spell_id
        session_state.records[0].context_heading = "General Notes"

        def failing_stage2_caller(_request: Stage2ExtractionInput) -> dict[str, object]:
            raise RuntimeError("stage2 transport error")

        extract_all_pending(
            session_state,
            config=AppConfig(stage2_max_attempts=1),
            stage2_caller=failing_stage2_caller,
        )

        self.assertEqual(session_state.records[0].status, SpellRecordStatus.NEEDS_REVIEW)
        placeholder_spell = session_state.records[0].canonical_spell
        if placeholder_spell is None:
            self.fail("Expected placeholder canonical spell after retries are exhausted.")
        self.assertEqual(placeholder_spell.class_list, ClassList.WIZARD)
        self.assertEqual(placeholder_spell.level, 0)
        self.assertIsNone(placeholder_spell.sphere)


class ReviewFlowServiceTests(unittest.TestCase):
    def _build_review_session(self) -> SessionState:
        routed_document = _build_routed_document(
            [["Wizard Spells", "Magic Missile", "Range: 30 yards", "Duration: 1 round"]]
        )
        review_spell = _canonical_spell(
            name="Magic Missile",
            level=1,
            start_line=1,
            end_line=4,
        )
        confirmed_spell = _canonical_spell(
            name="Shield",
            level=1,
            start_line=0,
            end_line=1,
        )
        return SessionState(
            source_sha256_hex=SHA_DISCOVERY,
            last_open_path=str(routed_document.source_path),
            coordinate_map=routed_document.coordinate_map,
            records=[
                SpellRecord(
                    spell_id="review-1",
                    status=SpellRecordStatus.NEEDS_REVIEW,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=1,
                    boundary_end_line=4,
                    context_heading="Wizard Spells",
                    canonical_spell=review_spell,
                ),
                SpellRecord(
                    spell_id="confirmed-1",
                    status=SpellRecordStatus.CONFIRMED,
                    extraction_order=1,
                    section_order=1,
                    boundary_start_line=0,
                    boundary_end_line=1,
                    context_heading="Wizard Spells",
                    canonical_spell=confirmed_spell,
                ),
            ],
            selected_spell_id="review-1",
        )

    def test_apply_review_edits_mutates_draft_only(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        original_canonical = record.canonical_spell

        apply_review_edits(
            record,
            draft_updates={"range": "60 yards", "review_notes": "Draft edit"},
            config=AppConfig(),
        )

        self.assertTrue(record.draft_dirty)
        self.assertIsNotNone(record.draft_spell)
        self.assertEqual(record.draft_spell.range, "60 yards")
        self.assertEqual(record.canonical_spell, original_canonical)

    def test_accept_review_moves_record_to_confirmed(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={"range": "45 yards"},
            config=AppConfig(),
        )

        accepted = accept_review_record(session_state, spell_id="review-1")

        self.assertTrue(accepted)
        self.assertEqual(record.status, SpellRecordStatus.CONFIRMED)
        self.assertEqual(record.canonical_spell.range, "45 yards")
        self.assertIsNone(record.draft_spell)
        self.assertFalse(record.draft_dirty)

    def test_accept_review_record_learns_custom_school_and_sphere_on_commit(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        config = AppConfig()
        apply_review_edits(
            record,
            draft_updates={
                "class_list": ClassList.PRIEST,
                "school": [" Runecraft ", "Runecraft", "Sigilry"],
                "sphere": [" Twilight ", "Twilight"],
            },
            config=config,
        )

        accepted = accept_review_record(session_state, spell_id="review-1", config=config)

        self.assertTrue(accepted)
        self.assertEqual(config.custom_schools, ["Runecraft", "Sigilry"])
        self.assertEqual(config.custom_spheres, ["Twilight"])

    def test_accept_review_duplicate_skip_leaves_review_record_uncommitted(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={"name": "Shield", "class_list": ClassList.WIZARD},
            config=AppConfig(),
        )

        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.SKIP,
        )

        self.assertFalse(accepted)
        self.assertEqual(record.status, SpellRecordStatus.NEEDS_REVIEW)
        self.assertTrue(record.draft_dirty)

    def test_accept_review_duplicate_overwrite_replaces_confirmed_and_keeps_review_record(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={"name": "Shield", "description": "Review replacement description."},
            config=AppConfig(),
        )

        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.OVERWRITE,
        )

        self.assertTrue(accepted)
        spell_ids = [current.spell_id for current in session_state.records]
        self.assertEqual(spell_ids, ["review-1"])
        self.assertEqual(
            session_state.records[0].canonical_spell.description,
            "Review replacement description.",
        )
        self.assertEqual(session_state.records[0].status, SpellRecordStatus.CONFIRMED)

    def test_accept_review_duplicate_overwrite_preserves_review_provenance_consistency(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={
                "name": "Shield",
                "source_document": "UserEdited.docx",
                "source_page": 77,
                "extraction_start_line": 999,
                "extraction_end_line": 1001,
            },
            config=AppConfig(),
        )

        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.OVERWRITE,
        )

        self.assertTrue(accepted)
        self.assertEqual([current.spell_id for current in session_state.records], ["review-1"])
        self.assertEqual(record.status, SpellRecordStatus.CONFIRMED)
        self.assertEqual(record.boundary_start_line, 1)
        self.assertEqual(record.boundary_end_line, 4)
        self.assertEqual(record.canonical_spell.extraction_start_line, record.boundary_start_line)
        self.assertEqual(record.canonical_spell.extraction_end_line, record.boundary_end_line)
        self.assertEqual(record.canonical_spell.source_document, "spellbook.pdf")
        self.assertEqual(record.canonical_spell.source_page, 0)

    def test_accept_review_duplicate_keep_both_confirms_review_record(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={"name": "Shield"},
            config=AppConfig(),
        )

        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.KEEP_BOTH,
        )

        self.assertTrue(accepted)
        self.assertEqual(record.status, SpellRecordStatus.CONFIRMED)
        self.assertEqual(len(session_state.records), 2)

    def test_save_confirmed_changes_raises_explicit_duplicate_error(self) -> None:
        session_state = self._build_review_session()
        session_state.records.append(
            SpellRecord(
                spell_id="confirmed-2",
                status=SpellRecordStatus.CONFIRMED,
                extraction_order=2,
                section_order=2,
                boundary_start_line=5,
                boundary_end_line=6,
                canonical_spell=_canonical_spell(
                    name="Magic Missile",
                    level=1,
                    start_line=5,
                    end_line=6,
                ),
            )
        )
        confirmed_record = session_state.records[1]
        apply_review_edits(
            confirmed_record,
            draft_updates={"name": "Magic Missile"},
            config=AppConfig(),
        )

        with self.assertRaises(DuplicateConfirmedSpellError):
            save_confirmed_changes(session_state, spell_id="confirmed-1")

    def test_get_confirmed_save_duplicate_conflict_surfaces_same_collision_as_save_m001(
        self,
    ) -> None:
        session_state = self._build_review_session()
        session_state.records.append(
            SpellRecord(
                spell_id="confirmed-2",
                status=SpellRecordStatus.CONFIRMED,
                extraction_order=2,
                section_order=2,
                boundary_start_line=5,
                boundary_end_line=6,
                canonical_spell=_canonical_spell(
                    name="Magic Missile",
                    level=1,
                    start_line=5,
                    end_line=6,
                ),
            )
        )
        confirmed_record = session_state.records[1]
        apply_review_edits(
            confirmed_record,
            draft_updates={"name": "Magic Missile"},
            config=AppConfig(),
        )

        conflict = get_confirmed_save_duplicate_conflict(session_state, spell_id="confirmed-1")

        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.spell_id, "confirmed-2")

    def test_get_confirmed_save_duplicate_conflict_none_when_no_collision_m001(self) -> None:
        session_state = self._build_review_session()

        self.assertIsNone(get_confirmed_save_duplicate_conflict(session_state, spell_id="confirmed-1"))

    def test_get_confirmed_save_duplicate_conflict_none_for_non_confirmed_record_m001(
        self,
    ) -> None:
        session_state = self._build_review_session()

        self.assertIsNone(get_confirmed_save_duplicate_conflict(session_state, spell_id="review-1"))

    def test_save_confirmed_changes_learns_custom_school_and_sphere_on_commit(self) -> None:
        session_state = self._build_review_session()
        config = AppConfig(
            custom_schools=["Runecraft"],
            custom_spheres=[" Twilight "],
        )
        confirmed_record = session_state.records[1]
        apply_review_edits(
            confirmed_record,
            draft_updates={
                "class_list": ClassList.PRIEST,
                "school": ["Runecraft", "Runecraft", "Chronomancy "],
                "sphere": ["Twilight", "Twilight", "Stars "],
            },
            config=config,
        )

        save_confirmed_changes(session_state, spell_id="confirmed-1", config=config)

        self.assertEqual(config.custom_schools, ["Runecraft", "Chronomancy"])
        self.assertEqual(config.custom_spheres, ["Twilight", "Stars"])

    def test_save_confirmed_changes_does_not_learn_unknown_placeholder_terms(self) -> None:
        session_state = self._build_review_session()
        config = AppConfig()
        confirmed_record = session_state.records[1]
        apply_review_edits(
            confirmed_record,
            draft_updates={
                "class_list": ClassList.PRIEST,
                "school": ["Unknown", "  UNKNOWN ", "Chronomancy"],
                "sphere": ["unknown", " Stars "],
            },
            config=config,
        )

        save_confirmed_changes(session_state, spell_id="confirmed-1", config=config)

        self.assertEqual(config.custom_schools, ["Chronomancy"])
        self.assertEqual(config.custom_spheres, ["Stars"])

    def test_discard_record_draft_clears_draft_only(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={"range": "50 yards"},
            config=AppConfig(),
        )

        discard_record_draft(record)

        self.assertFalse(record.draft_dirty)
        self.assertIsNone(record.draft_spell)
        self.assertEqual(record.canonical_spell.range, "30 yards")

    def test_delete_record_removes_selected_record(self) -> None:
        session_state = self._build_review_session()

        deleted = delete_record(session_state, spell_id="review-1")

        self.assertTrue(deleted)
        self.assertEqual([record.spell_id for record in session_state.records], ["confirmed-1"])
        self.assertIsNone(session_state.selected_spell_id)

    def test_delete_record_returns_false_when_record_missing(self) -> None:
        session_state = self._build_review_session()
        original_record_ids = [record.spell_id for record in session_state.records]
        original_selected_spell_id = session_state.selected_spell_id

        deleted = delete_record(session_state, spell_id="missing")

        self.assertFalse(deleted)
        self.assertEqual([record.spell_id for record in session_state.records], original_record_ids)
        self.assertEqual(session_state.selected_spell_id, original_selected_spell_id)

    def test_get_review_draft_returns_existing_draft_instance(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        draft_spell = record.canonical_spell.model_copy(deep=True)
        draft_spell.range = "75 yards"
        record.draft_spell = draft_spell
        record.draft_dirty = True

        result = get_review_draft(record)

        self.assertIs(result, draft_spell)
        self.assertEqual(result.range, "75 yards")

    def test_get_review_draft_copies_canonical_spell_when_draft_missing(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        canonical_spell = record.canonical_spell
        if canonical_spell is None:
            self.fail("Expected canonical spell for review record.")

        result = get_review_draft(record)
        original_school = list(canonical_spell.school)
        original_components = list(canonical_spell.components)
        result.range = "120 yards"
        result.school.append("illusion")
        result.components.append("M")

        self.assertIsNot(result, canonical_spell)
        self.assertIsNot(result.school, canonical_spell.school)
        self.assertIsNot(result.components, canonical_spell.components)
        self.assertEqual(result.range, "120 yards")
        self.assertEqual(canonical_spell.range, "30 yards")
        self.assertEqual(result.school, [*original_school, "illusion"])
        self.assertEqual(canonical_spell.school, original_school)
        self.assertEqual(result.components, [*original_components, "M"])
        self.assertEqual(canonical_spell.components, original_components)

    def test_reextract_merges_into_draft_and_records_alt_conflict_candidates(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]
        apply_review_edits(
            record,
            draft_updates={
                "range": "60 yards",
                "duration": "2 rounds",
                "review_notes": "Manual draft note.",
            },
            config=AppConfig(),
        )

        def stage2_caller(request: Stage2ExtractionInput) -> dict[str, object]:
            self.assertEqual(request.focus_prompt, "Improve range and description")
            return {
                **_spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=request.record.boundary_start_line,
                    end_line=request.record.boundary_end_line,
                ),
                "range": "90 yards",
                "duration": "1 round",
                "description": "Improved description from re-extract.",
                "review_notes": "Model candidate.",
                "needs_review": True,
                "confidence": 0.4,
            }

        merged = reextract_record_into_draft(
            session_state,
            spell_id="review-1",
            focus_prompt="Improve range and description",
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=stage2_caller,
        )

        self.assertEqual(merged.description, "Improved description from re-extract.")
        self.assertEqual(merged.range, "60 yards")
        self.assertEqual(merged.duration, "2 rounds")
        self.assertTrue(record.draft_dirty)
        self.assertEqual(record.canonical_spell.range, "30 yards")
        alt_tags = parse_alt_tags(merged.review_notes)
        self.assertEqual(alt_tags.get("range"), "90 yards")

    def test_reextract_rejects_pending_records(self) -> None:
        session_state = self._build_review_session()
        session_state.records[0].status = SpellRecordStatus.PENDING_EXTRACTION

        with self.assertRaises(InvalidRecordStateError):
            reextract_record_into_draft(
                session_state,
                spell_id="review-1",
                focus_prompt="Improve description",
                config=AppConfig(stage2_max_attempts=1),
                stage2_caller=lambda _request: _spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=1,
                    end_line=4,
                ),
            )

    def test_reextract_overrides_model_provenance_with_record_boundaries(self) -> None:
        session_state = self._build_review_session()
        record = session_state.records[0]

        def stage2_caller(request: Stage2ExtractionInput) -> dict[str, object]:
            return {
                **_spell_payload(
                    name="Magic Missile",
                    level=1,
                    start_line=999,
                    end_line=1000,
                ),
                "description": "Improved description from re-extract.",
                "source_document": "hallucinated-reextract.pdf",
                "source_page": 4242,
                "extraction_start_line": 999,
                "extraction_end_line": 1000,
            }

        merged = reextract_record_into_draft(
            session_state,
            spell_id="review-1",
            focus_prompt="Improve description",
            config=AppConfig(stage2_max_attempts=2),
            stage2_caller=stage2_caller,
        )

        self.assertEqual(merged.description, "Improved description from re-extract.")
        self.assertEqual(merged.source_document, "spellbook.pdf")
        self.assertEqual(merged.source_page, 0)
        self.assertEqual(merged.extraction_start_line, record.boundary_start_line)
        self.assertEqual(merged.extraction_end_line, record.boundary_end_line)

    def test_save_confirmed_changes_raises_record_not_found(self) -> None:
        session_state = self._build_review_session()

        with self.assertRaises(RecordNotFoundError):
            save_confirmed_changes(session_state, spell_id="missing")

    def test_duplicate_detection_normalizes_extra_internal_spaces_in_confirmed_name(self) -> None:
        session_state = self._build_review_session()
        # Confirmed record has extra internal spaces in the name.
        confirmed_record = session_state.records[1]
        confirmed_record.canonical_spell = confirmed_record.canonical_spell.model_copy(
            update={"name": "Magic   Missile"}
        )
        # Review record draft uses the canonical single-space spelling.
        review_record = session_state.records[0]
        apply_review_edits(
            review_record,
            draft_updates={"name": "Magic Missile"},
            config=AppConfig(),
        )

        conflict = get_confirmed_save_duplicate_conflict(session_state, spell_id="confirmed-1")
        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.SKIP,
        )

        self.assertIsNone(conflict)  # confirmed-1 draft == confirmed-1 canonical (same record excluded)
        self.assertFalse(accepted)  # review draft collides with the extra-spaced confirmed name

    def test_duplicate_detection_normalizes_mixed_case_in_confirmed_name(self) -> None:
        session_state = self._build_review_session()
        # Confirmed record has mixed/uppercase name.
        confirmed_record = session_state.records[1]
        confirmed_record.canonical_spell = confirmed_record.canonical_spell.model_copy(
            update={"name": "MAGIC MISSILE"}
        )
        # Review record draft uses the canonical mixed-case spelling.
        review_record = session_state.records[0]
        apply_review_edits(
            review_record,
            draft_updates={"name": "Magic Missile"},
            config=AppConfig(),
        )

        accepted = accept_review_record(
            session_state,
            spell_id="review-1",
            duplicate_resolution=DuplicateResolutionStrategy.SKIP,
        )

        self.assertFalse(accepted)  # review draft collides with the uppercased confirmed name


if __name__ == "__main__":
    unittest.main()