## Context

The revised spec treats spell discovery as a separate workflow stage from Stage 2 extraction. Discovery must scan pages sequentially, carry heading context across pages, and create pending records only when a span is closed by the next spell start or by end-of-file.

The change depends on the core session models and on document-ingestion output. It does not depend on Stage 2 extraction or the review UI.

## Goals / Non-Goals

**Goals:**
- Implement Stage 1 request formatting and JSON response parsing.
- Maintain sequential discovery state across pages.
- Close spell boundaries correctly for multi-page spell descriptions.
- Write pending records to session state and restore them without re-discovery.
- Keep `Detect Spells` separate from later extraction commands.

**Non-Goals:**
- Implement Stage 2 extraction.
- Implement review editing.
- Implement export.

## Decisions

### Discovery stays sequential even if later extraction is parallel
- Page order matters because headings and spell spans can cross page boundaries.
- Sequential state keeps `active_heading` and stop conditions deterministic.

Alternative considered:
- Parallel page discovery.
- Rejected because heading carry-forward and span closure become ambiguous across out-of-order results.

### Use absolute line numbers in the Stage 1 prompt
- Absolute line numbers let the model return exact start offsets without relying on token-based or newline-based counting.
- The pending queue can reuse those line numbers as stable span anchors.

Alternative considered:
- Let the model infer line positions from raw markdown.
- Rejected because line counting hallucinations would make downstream spans unstable.

### Create pending records only when the span is closed
- A record becomes actionable only after the next start line or EOF defines its end.
- This preserves full multi-page spell descriptions for Stage 2 input.

Alternative considered:
- Create a final pending record immediately at each start line.
- Rejected because the record would not know where the spell ends.

## Risks / Trade-offs

- Stage 1 may miss starts or misread headings → Keep the JSON parser strict and cover stop conditions with tests.
- Empty-page cutoff can stop too early on noisy scans → Keep the cutoff configurable and reset on headings or spell hits.
- Pending spans can be wrong if absolute line numbers drift → Tie them directly to the ingested coordinate map and test cross-page cases.

## Migration Plan

- No migration is required beyond using the session-state envelope from the core-model change.

## Open Questions

- None for this change.
