from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig
from app.models import CoordinateAwareTextMap, TextRegion
from app.pipeline.identity import DocumentIdentityMetadata
from app.pipeline.ingestion import RoutedDocument
from app.session import SessionState, SpellRecord, SpellRecordStatus
from extract_cli import run_extraction_cli


class ExtractCliTests(unittest.TestCase):
    def _build_routed_document(self) -> RoutedDocument:
        return RoutedDocument(
            source_path=Path(r"C:\\tmp\\spellbook.pdf"),
            source_sha256_hex="a" * 64,
            file_type="pdf",
            ingestion_mode="pdf_digital",
            markdown_text="Magic Missile",
            coordinate_map=CoordinateAwareTextMap(
                lines=[("Magic Missile", TextRegion(page=0, bbox=(0.0, 0.0, 10.0, 1.0)))]
            ),
            default_source_pages=[1],
            identity=DocumentIdentityMetadata(
                source_sha256_hex="a" * 64,
                source_display_name="Player's Handbook",
                page_offset=0,
                force_ocr=False,
            ),
        )

    def _build_session(self) -> SessionState:
        return SessionState(
            source_sha256_hex="a" * 64,
            last_open_path=r"C:\\tmp\\spellbook.pdf",
            coordinate_map=CoordinateAwareTextMap(
                lines=[("Magic Missile", TextRegion(page=0, bbox=(0.0, 0.0, 10.0, 1.0)))]
            ),
            records=[
                SpellRecord(
                    spell_id="pending-a",
                    status=SpellRecordStatus.PENDING_EXTRACTION,
                    extraction_order=0,
                    section_order=0,
                    boundary_start_line=0,
                    boundary_end_line=1,
                )
            ],
            selected_spell_id="pending-a",
        )

    def test_run_extraction_cli_uses_extract_all_by_default(self) -> None:
        routed_document = self._build_routed_document()
        session_state = self._build_session()
        all_calls = 0
        selected_calls = 0
        saved_calls = 0

        def extract_all_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            nonlocal all_calls
            all_calls += 1
            state.records[0].status = SpellRecordStatus.CONFIRMED
            return state

        def extract_selected_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            nonlocal selected_calls
            selected_calls += 1
            return state

        def save_session_fn(state: SessionState, *, session_path: str | Path | None = None) -> Path:
            nonlocal saved_calls
            saved_calls += 1
            return Path(session_path or "session.json")

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = run_extraction_cli(
                [r"C:\\tmp\\spellbook.pdf", "--session-path", r"C:\\tmp\\session.json"],
                load_config=lambda _config_path: AppConfig(),
                route_document_fn=lambda _source_path, *, config: routed_document,
                open_or_restore_session_fn=lambda _doc, *, config, session_path: session_state,
                extract_selected_fn=extract_selected_fn,
                extract_all_fn=extract_all_fn,
                save_session_fn=save_session_fn,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(all_calls, 1)
        self.assertEqual(selected_calls, 0)
        self.assertEqual(saved_calls, 1)
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["status_counts"]["confirmed"], 1)

    def test_run_extraction_cli_uses_extract_selected_when_requested(self) -> None:
        routed_document = self._build_routed_document()
        session_state = self._build_session()
        all_calls = 0
        selected_calls = 0

        def extract_all_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            nonlocal all_calls
            all_calls += 1
            return state

        def extract_selected_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            nonlocal selected_calls
            selected_calls += 1
            state.records[0].status = SpellRecordStatus.NEEDS_REVIEW
            return state

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = run_extraction_cli(
                [
                    r"C:\\tmp\\spellbook.pdf",
                    "--selected-only",
                    "--session-path",
                    r"C:\\tmp\\session.json",
                ],
                load_config=lambda _config_path: AppConfig(),
                route_document_fn=lambda _source_path, *, config: routed_document,
                open_or_restore_session_fn=lambda _doc, *, config, session_path: session_state,
                extract_selected_fn=extract_selected_fn,
                extract_all_fn=extract_all_fn,
                save_session_fn=lambda _state, *, session_path: Path(session_path or "session.json"),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(selected_calls, 1)
        self.assertEqual(all_calls, 0)
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["status_counts"]["needs_review"], 1)

    def test_run_extraction_cli_uses_returned_selected_session_state(self) -> None:
        routed_document = self._build_routed_document()
        opened_session = self._build_session()
        returned_session = opened_session.model_copy(deep=True)
        returned_session.records[0].status = SpellRecordStatus.CONFIRMED
        saved_states: list[SessionState] = []

        def extract_selected_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            self.assertIs(state, opened_session)
            return returned_session

        def save_session_fn(state: SessionState, *, session_path: str | Path | None = None) -> Path:
            saved_states.append(state)
            return Path(session_path or "session.json")

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = run_extraction_cli(
                [r"C:\\tmp\\spellbook.pdf", "--selected-only"],
                load_config=lambda _config_path: AppConfig(),
                route_document_fn=lambda _source_path, *, config: routed_document,
                open_or_restore_session_fn=lambda _doc, *, config, session_path: opened_session,
                extract_selected_fn=extract_selected_fn,
                extract_all_fn=lambda _state, *, config: self.fail("unexpected extract_all_fn call"),
                save_session_fn=save_session_fn,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved_states, [returned_session])
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["record_count"], len(returned_session.records))
        self.assertEqual(payload["status_counts"]["confirmed"], 1)
        self.assertEqual(payload["status_counts"]["pending_extraction"], 0)

    def test_run_extraction_cli_uses_returned_all_session_state(self) -> None:
        routed_document = self._build_routed_document()
        opened_session = self._build_session()
        returned_session = opened_session.model_copy(deep=True)
        returned_session.records[0].status = SpellRecordStatus.NEEDS_REVIEW
        saved_states: list[SessionState] = []

        def extract_all_fn(state: SessionState, *, config: AppConfig) -> SessionState:
            self.assertIs(state, opened_session)
            return returned_session

        def save_session_fn(state: SessionState, *, session_path: str | Path | None = None) -> Path:
            saved_states.append(state)
            return Path(session_path or "session.json")

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = run_extraction_cli(
                [r"C:\\tmp\\spellbook.pdf"],
                load_config=lambda _config_path: AppConfig(),
                route_document_fn=lambda _source_path, *, config: routed_document,
                open_or_restore_session_fn=lambda _doc, *, config, session_path: opened_session,
                extract_selected_fn=(
                    lambda _state, *, config: self.fail("unexpected extract_selected_fn call")
                ),
                extract_all_fn=extract_all_fn,
                save_session_fn=save_session_fn,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved_states, [returned_session])
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["record_count"], len(returned_session.records))
        self.assertEqual(payload["status_counts"]["needs_review"], 1)
        self.assertEqual(payload["status_counts"]["pending_extraction"], 0)

    def test_run_extraction_cli_supports_in_place_extract_mutator_returning_none(self) -> None:
        routed_document = self._build_routed_document()
        opened_session = self._build_session()
        saved_states: list[SessionState] = []

        def extract_selected_fn(state: SessionState, *, config: AppConfig) -> None:
            state.records[0].status = SpellRecordStatus.CONFIRMED
            return None

        def save_session_fn(state: SessionState, *, session_path: str | Path | None = None) -> Path:
            saved_states.append(state)
            return Path(session_path or "session.json")

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = run_extraction_cli(
                [r"C:\\tmp\\spellbook.pdf", "--selected-only"],
                load_config=lambda _config_path: AppConfig(),
                route_document_fn=lambda _source_path, *, config: routed_document,
                open_or_restore_session_fn=lambda _doc, *, config, session_path: opened_session,
                extract_selected_fn=extract_selected_fn,
                extract_all_fn=lambda _state, *, config: self.fail("unexpected extract_all_fn call"),
                save_session_fn=save_session_fn,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved_states, [opened_session])
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["status_counts"]["confirmed"], 1)
        self.assertEqual(payload["status_counts"]["pending_extraction"], 0)


if __name__ == "__main__":
    unittest.main()

