from __future__ import annotations

import math
from enum import Enum
from typing import Any

from app.utils.review_notes import strip_alt_tags
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)


class SpellSchool(str, Enum):
    ABJURATION = "Abjuration"
    AIR = "Air"
    ALCHEMY = "Alchemy"
    ALTERATION = "Alteration"
    ARTIFACE = "Artifice"
    CALLING = "Calling"
    CHARM = "Charm"
    CONJURATION = "Conjuration"
    CONJURATION_SUMMONING = "Conjuration/Summoning"
    CREATION = "Creation"
    DIMENSION = "Dimension"
    DIVINATION = "Divination"
    EARTH = "Earth"
    ENCHANTMENT = "Enchantment"
    ENCHANTMENT_CHARM = "Enchantment/Charm"
    EVOCATION = "Evocation"
    FIRE = "Fire"
    FORCE = "Force"
    GEOMETRY = "Geometry"
    ILLUSION = "Illusion"
    ILLUSION_PHANTASM = "Illusion/Phantasm"
    INVOCATION = "Invocation"
    INVOCATION_EVOCATION = "Invocation/Evocation"
    NECROMANCY = "Necromancy"
    PHANTASM = "Phantasm"
    SHADOW = "Shadow"
    SUMMONING = "Summoning"
    TELEPORTATION = "Teleportation"
    TEMPORAL = "Temporal"
    WATER = "Water"
    WILD_MAGIC = "Wild Magic"
    UNIVERSAL = "Universal"


class PriestSphere(str, Enum):
    ALL = "All"
    ANIMAL = "Animal"
    ASTRAL = "Astral"
    CHAOS = "Chaos"
    CHARM = "Charm"
    COMBAT = "Combat"
    CREATION = "Creation"
    DESERT = "Desert"
    DESTINY = "Destiny"
    DIVINATION = "Divination"
    DROW = "Drow"
    ELEMENTAL_AIR = "Elemental Air"
    ELEMENTAL_EARTH = "Elemental Earth"
    ELEMENTAL_FIRE = "Elemental Fire"
    ELEMENTAL_WATER = "Elemental Water"
    ELEMENTAL_RAIN = "Elemental Rain"
    ELEMENTAL_SUN = "Elemental Sun"
    EVIL = "Evil"
    FATE = "Fate"
    GOOD = "Good"
    GUARDIAN = "Guardian"
    HEALING = "Healing"
    LAW = "Law"
    MAGMA = "Magma"
    NECROMANTIC = "Necromantic"
    NUMBERS = "Numbers"
    PLANT = "Plant"
    PROTECTION = "Protection"
    SILT = "Silt"
    SUMMONING = "Summoning"
    SUN = "Sun"
    THOUGHT = "Thought"
    TIME = "Time"
    TRAVELERS = "Travelers"
    WAR = "War"
    WEATHER = "Weather"


class ClassList(str, Enum):
    WIZARD = "Wizard"
    PRIEST = "Priest"


class Tradition(str, Enum):
    ARCANE = "Arcane"
    DIVINE = "Divine"


class Component(str, Enum):
    V = "V"
    S = "S"
    M = "M"


SpellLevel = int


def _append_note(existing: str | None, extra: str) -> str:
    existing_text = (existing or "").strip()
    extra_text = extra.strip()
    if not existing_text:
        return extra_text
    if not extra_text:
        return existing_text
    if "ALT[" in existing_text and not strip_alt_tags(existing_text):
        return f"{existing_text}\n{extra_text}"
    if existing_text.endswith((".", "!", "?")):
        return f"{existing_text} {extra_text}"
    return f"{existing_text}; {extra_text}"


def _context_values(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def _parse_class_list(value: Any) -> ClassList | None:
    if isinstance(value, ClassList):
        return value
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    for class_item in ClassList:
        if class_item.value.lower() == normalized:
            return class_item
    return None


def _parse_level(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "cantrip":
            return 0
        if normalized == "quest":
            return 8
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default


def _clean_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item:
            cleaned.append(item)
    return cleaned


def _parse_components(values: list[str] | None) -> tuple[list[Component], list[str]]:
    if not values:
        return [], []

    parsed: list[Component] = []
    rejected: list[str] = []

    for value in values:
        if not isinstance(value, str):
            rejected.append(str(value))
            continue

        normalized = value.replace("/", ",").replace(";", ",")
        tokens: list[str] = []
        for part in normalized.split(","):
            tokens.extend(part.strip().upper().split())

        if not tokens:
            continue

        for token in tokens:
            try:
                parsed.append(Component(token))
            except ValueError:
                rejected.append(token)

    return parsed, rejected


def _format_validation_errors(error: ValidationError) -> str:
    parts: list[str] = []
    for issue in error.errors():
        loc = ".".join(str(piece) for piece in issue.get("loc", ()))
        msg = issue.get("msg", "Invalid value")
        if loc:
            parts.append(f"{loc}: {msg}")
        else:
            parts.append(str(msg))
    return "; ".join(parts)


class Spell(BaseModel):
    name: str
    class_list: ClassList
    level: SpellLevel

    @computed_field
    @property
    def tradition(self) -> Tradition:
        return (
            Tradition.ARCANE
            if self.class_list == ClassList.WIZARD
            else Tradition.DIVINE
        )

    school: list[str]
    sphere: list[str] | None = None

    range: str
    components: list[Component]
    duration: str
    casting_time: str
    area_of_effect: str
    saving_throw: str

    description: str
    reversible: bool = False

    source_document: str
    source_page: int | None = None

    confidence: float = 1.0
    needs_review: bool = False
    review_notes: str | None = None
    extraction_start_line: int = -1
    extraction_end_line: int = -1

    @field_validator("level", mode="before")
    @classmethod
    def normalise_level(cls, value: Any) -> int:
        parsed_level = _parse_level(value)
        if parsed_level is None:
            raise ValueError(f"Cannot parse level: {value!r}")
        return parsed_level

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("Confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_school_sphere(self) -> Spell:
        if not self.school:
            raise ValueError("All spells must have at least one school.")
        if self.class_list == ClassList.WIZARD and self.sphere is not None:
            raise ValueError("Wizard spells must not have a sphere.")
        if self.class_list == ClassList.PRIEST and not self.sphere:
            raise ValueError("Priest spells must have at least one sphere.")
        return self

    @model_validator(mode="after")
    def flag_unknown_school_sphere(self, info: ValidationInfo) -> Spell:
        context = info.context if isinstance(info.context, dict) else {}
        custom_schools = _context_values(context.get("custom_schools"))
        custom_spheres = _context_values(context.get("custom_spheres"))

        known_schools = {school.value for school in SpellSchool} | custom_schools
        known_spheres = {sphere.value for sphere in PriestSphere} | custom_spheres

        unknown_schools = [item for item in self.school if item not in known_schools]
        unknown_spheres = [item for item in (self.sphere or []) if item not in known_spheres]

        if unknown_schools or unknown_spheres:
            self.needs_review = True
            notes: list[str] = []
            if unknown_schools:
                notes.append(f"Unknown school(s): {', '.join(unknown_schools)}.")
            if unknown_spheres:
                notes.append(f"Unknown sphere(s): {', '.join(unknown_spheres)}.")
            self.review_notes = _append_note(self.review_notes, " ".join(notes))

        return self

    @model_validator(mode="after")
    def validate_level_range_by_type(self) -> Spell:
        if self.class_list == ClassList.WIZARD and not (0 <= self.level <= 9):
            raise ValueError(f"Wizard spell level must be 0-9, got {self.level}")
        if self.class_list == ClassList.PRIEST and not (1 <= self.level <= 8):
            raise ValueError(f"Priest spell level must be 1-8 (8 = Quest), got {self.level}")
        return self


class LaxSpell(BaseModel):
    name: str | None = None
    class_list: str | None = None
    level: str | int | None = None
    school: list[str] | None = None
    sphere: list[str] | None = None

    range: str | None = None
    components: list[str] | None = None
    duration: str | None = None
    casting_time: str | None = None
    area_of_effect: str | None = None
    saving_throw: str | None = None

    description: str | None = None
    reversible: bool | None = None

    source_document: str | None = None
    source_page: int | None = None

    confidence: float | None = None
    needs_review: bool | None = None
    review_notes: str | None = None
    extraction_start_line: int | None = None
    extraction_end_line: int | None = None

    def to_spell(
        self,
        custom_schools: list[str] | None = None,
        custom_spheres: list[str] | None = None,
    ) -> Spell:
        payload = self.model_dump(exclude_none=True)
        validation_context: dict[str, list[str]] = {}
        if custom_schools is not None:
            validation_context["custom_schools"] = custom_schools
        if custom_spheres is not None:
            validation_context["custom_spheres"] = custom_spheres
        context_arg: dict[str, list[str]] | None = validation_context or None

        try:
            return Spell.model_validate(payload, context=context_arg)
        except ValidationError as error:
            parsed_class = _parse_class_list(self.class_list) or ClassList.WIZARD
            parsed_level = _parse_level(self.level)
            fallback_level = parsed_level if parsed_level is not None else 0

            extra_notes: list[str] = []
            if parsed_class == ClassList.WIZARD and not (0 <= fallback_level <= 9):
                fallback_level = 0
                extra_notes.append("Level fell outside Wizard range and was reset to 0.")

            if parsed_class == ClassList.PRIEST and not (1 <= fallback_level <= 8):
                parsed_class = ClassList.WIZARD
                fallback_level = 0
                extra_notes.append(
                    "Class fell back to Wizard because Priest level was invalid or missing."
                )

            school_values = _clean_string_list(self.school)
            if not school_values:
                school_values = ["Unknown"]

            sphere_values = _clean_string_list(self.sphere)
            if parsed_class == ClassList.PRIEST:
                sphere_field: list[str] | None = sphere_values or ["Unknown"]
            else:
                sphere_field = None

            parsed_components, rejected_components = _parse_components(self.components)
            if rejected_components:
                extra_notes.append(
                    "Dropped unparseable component value(s): "
                    + ", ".join(rejected_components)
                    + "."
                )

            review_text = _append_note(
                self.review_notes,
                f"Validation errors: {_format_validation_errors(error)}",
            )
            for note in extra_notes:
                review_text = _append_note(review_text, note)

            fallback_payload: dict[str, Any] = {
                "name": _coerce_str(self.name),
                "class_list": parsed_class,
                "level": fallback_level,
                "school": school_values,
                "sphere": sphere_field,
                "range": _coerce_str(self.range),
                "components": parsed_components,
                "duration": _coerce_str(self.duration),
                "casting_time": _coerce_str(self.casting_time),
                "area_of_effect": _coerce_str(self.area_of_effect),
                "saving_throw": _coerce_str(self.saving_throw),
                "description": _coerce_str(self.description),
                "reversible": _coerce_bool(self.reversible, default=False),
                "source_document": _coerce_str(self.source_document),
                "source_page": _coerce_optional_int(self.source_page),
                "confidence": 0.0,
                "needs_review": True,
                "review_notes": review_text,
                "extraction_start_line": _coerce_int(self.extraction_start_line, -1),
                "extraction_end_line": _coerce_int(self.extraction_end_line, -1),
            }

            return Spell.model_validate(fallback_payload, context=context_arg)


class TextRegion(BaseModel):
    page: int = Field(ge=-1)
    bbox: tuple[float, float, float, float] | None = None
    char_offset: tuple[int, int] | None = None

    @model_validator(mode="after")
    def validate_source_coordinates(self) -> TextRegion:
        has_bbox = self.bbox is not None
        has_char_offset = self.char_offset is not None

        if has_bbox == has_char_offset:
            raise ValueError("Exactly one of bbox or char_offset must be provided.")

        if self.page == -1 and not has_char_offset:
            raise ValueError("DOCX regions (page=-1) must provide char_offset.")

        if self.page >= 0 and not has_bbox:
            raise ValueError("PDF regions (page>=0) must provide bbox.")

        if self.char_offset is not None:
            start, end = self.char_offset
            if start < 0 or end < 0:
                raise ValueError("char_offset values must be non-negative.")
            if end < start:
                raise ValueError("char_offset end must be greater than or equal to start.")

        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                raise ValueError("bbox values must be finite numbers.")
            if x1 < x0 or y1 < y0:
                raise ValueError(
                    "bbox max coordinates must be greater than or equal to min coordinates."
                )

        return self


class CoordinateAwareTextMap(BaseModel):
    lines: list[tuple[str, TextRegion]]

    def _slice_for_range(
        self,
        start_line: int,
        end_line: int,
    ) -> list[tuple[str, TextRegion]]:
        if start_line < 0 or end_line < 0:
            raise ValueError("start_line and end_line must be non-negative.")
        if start_line >= end_line:
            raise ValueError("end_line must be greater than start_line.")
        if start_line >= len(self.lines):
            raise ValueError("start_line is out of bounds for available lines.")
        capped_end = min(end_line, len(self.lines))
        return self.lines[start_line:capped_end]

    def get_line(self, line_index: int) -> str | None:
        if line_index < 0 or line_index >= len(self.lines):
            return None
        return self.lines[line_index][0]

    def get_region(self, line_index: int) -> TextRegion | None:
        if line_index < 0 or line_index >= len(self.lines):
            return None
        return self.lines[line_index][1]

    def regions_for_range(self, start_line: int, end_line: int) -> list[TextRegion]:
        return [region for _, region in self._slice_for_range(start_line, end_line)]

    def page_span(self, start_line: int, end_line: int) -> tuple[int, int]:
        pages = [
            region.page
            for _, region in self._slice_for_range(start_line, end_line)
            if region.page >= 0
        ]
        if not pages:
            return (-1, -1)
        return (min(pages), max(pages))