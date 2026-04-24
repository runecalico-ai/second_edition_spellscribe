from __future__ import annotations

import re

_ALT_TAG_RE = re.compile(
    r"ALT\[(?P<field>[^\]]+)\]=(?P<value>.*?)(?=\s+ALT\[|[\r\n]|$)"
)


def _encode_alt_value_for_single_line_tag(value: str) -> str:
    """Escape characters so ALT values stay on one line (H-001)."""
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _decode_alt_value_from_single_line_tag(value: str) -> str:
    """Reverse _encode_alt_value_for_single_line_tag; unknown \\x sequences keep the backslash."""
    out: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            next_char = value[index + 1]
            if next_char == "n":
                out.append("\n")
                index += 2
                continue
            if next_char == "r":
                out.append("\r")
                index += 2
                continue
            if next_char == "\\":
                out.append("\\")
                index += 2
                continue
        out.append(value[index])
        index += 1
    return "".join(out)


def parse_alt_tags(review_notes: str | None) -> dict[str, str]:
    """Return ALT[field]=value tags keyed by field name."""
    if not review_notes:
        return {}

    parsed: dict[str, str] = {}
    for match in _ALT_TAG_RE.finditer(review_notes):
        field = match.group("field").strip()
        value = _decode_alt_value_from_single_line_tag(match.group("value").strip())
        if not field:
            continue
        parsed[field] = value
    return parsed


def upsert_alt_tag(review_notes: str | None, field: str, value: str) -> str:
    """Insert or replace a single ALT[field]=value tag."""
    normalized_field = field.strip()
    if not normalized_field:
        raise ValueError("field must not be blank")
    semantic_value = value.strip()

    existing = parse_alt_tags(review_notes)
    existing[normalized_field] = semantic_value

    base_notes = strip_alt_tags(review_notes)
    tags = " ".join(
        f"ALT[{tag_field}]={_encode_alt_value_for_single_line_tag(tag_value)}"
        for tag_field, tag_value in sorted(existing.items(), key=lambda item: item[0].lower())
    )
    if base_notes and tags:
        return f"{base_notes} {tags}"
    if tags:
        return tags
    return base_notes


def strip_alt_tags(review_notes: str | None) -> str:
    """Remove ALT tags and normalize whitespace."""
    if not review_notes:
        return ""
    stripped = _ALT_TAG_RE.sub("", review_notes)
    return " ".join(stripped.split())

