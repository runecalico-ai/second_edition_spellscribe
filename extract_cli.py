from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from app.config import AppConfig
from app.pipeline.extraction import (
    extract_all_pending,
    extract_selected_pending,
    open_or_restore_discovery_session,
)
from app.pipeline.ingestion import RoutedDocument, route_document
from app.session import SessionState, save_session_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SpellScribe extraction for one source file.")
    parser.add_argument("source_path", help="Path to a source PDF or DOCX file.")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="Run Stage 2 only for selected pending spell.",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Optional config path. Defaults to SpellScribe app data config.",
    )
    parser.add_argument(
        "--session-path",
        default=None,
        help="Optional session path. Defaults to SpellScribe app data session.",
    )
    return parser


def run_extraction_cli(
    argv: Sequence[str] | None = None,
    *,
    load_config: Callable[[str | Path | None], AppConfig] | None = None,
    route_document_fn: Callable[..., RoutedDocument] = route_document,
    open_or_restore_session_fn: Callable[..., SessionState] = open_or_restore_discovery_session,
    extract_selected_fn: Callable[..., SessionState] = extract_selected_pending,
    extract_all_fn: Callable[..., SessionState] = extract_all_pending,
    save_session_fn: Callable[..., Path] = save_session_state,
) -> int:
    args = build_parser().parse_args(argv)
    config_loader = load_config or AppConfig.load
    config = config_loader(args.config_path)

    routed_document = route_document_fn(args.source_path, config=config)
    session_state = open_or_restore_session_fn(
        routed_document,
        config=config,
        session_path=args.session_path,
    )

    if args.selected_only:
        updated_session_state = extract_selected_fn(session_state, config=config)
    else:
        updated_session_state = extract_all_fn(session_state, config=config)

    if updated_session_state is not None:
        session_state = updated_session_state

    save_session_fn(session_state, session_path=args.session_path)

    status_counts = {
        "pending_extraction": 0,
        "needs_review": 0,
        "confirmed": 0,
    }
    for record in session_state.records:
        status_counts[record.status.value] = status_counts.get(record.status.value, 0) + 1

    print(
        json.dumps(
            {
                "source_path": str(args.source_path),
                "selected_only": bool(args.selected_only),
                "record_count": len(session_state.records),
                "status_counts": status_counts,
            },
            ensure_ascii=True,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_extraction_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

