from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import AppConfig
from app.models import ClassList, CoordinateAwareTextMap, Spell, TextRegion
from app.pipeline.extraction import (
    DiscoveryInterruptedError,
    DiscoveryPageInput,
    DiscoveryPageResponse,
    DiscoverySpellStart,
    _build_stage1_prompt_from_numbered_page,
    _read_keyring_api_key,
    _resolve_anthropic_api_key,
    detect_spells,
    detect_spells_with_autosave,
    number_markdown_lines,
    open_or_restore_discovery_session,
    parse_discovery_response,
    restore_discovery_session,
)
from app.pipeline.identity import DocumentIdentityMetadata
from app.pipeline.ingestion import RoutedDocument
from app.session import SessionState, SpellRecord, SpellRecordStatus, load_session_state, save_session_state
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
        self.assertEqual(
            messages,
            [
                {
                    "role": "user",
                    "content": messages[0]["content"],
                }
            ],
        )
        if not isinstance(messages, list):
            self.fail("Expected Anthropic user message list to be sent.")
        user_message = messages[0]["content"]
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


if __name__ == "__main__":
    unittest.main()