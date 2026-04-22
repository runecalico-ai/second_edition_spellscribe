# AD&D 2e Spell Extractor — Full Application Specification

> **How to use this document**
> Feed this entire file to Claude as the opening message of a new project, or break it into the numbered phases and hand them over one at a time. Each phase is self-contained and ends with a working, testable deliverable.

---

## 0. Project Overview

Build a Windows desktop companion application called **SpellScribe** that:

1. Accepts scanned PDFs or Word `.docx` files containing AD&D 2nd Edition spell descriptions.
2. Extracts individual spell stat blocks from those documents using OCR and Claude's API.
3. Validates each extracted spell against a strict AD&D 2e schema.
4. Presents uncertain or failed extractions in a human-review UI.
5. Exports the final collection as **JSON** and/or **Markdown** in a format ready to import into the main application.

The app is a **single-developer hobby tool** targeting Windows 10/11. It does not need a login system, cloud sync, or multi-user support. The UI must be functional and clean but does not need to be consumer-polished.

---

## 1. Technology Stack (fixed — do not substitute)

| Layer | Library / Tool | Version pin |
|---|---|---|
| GUI | `PySide6` | `>=6.7` |
| PDF ingestion (digital) | `PyMuPDF` + `pymupdf4llm` | latest |
| PDF ingestion (scanned) | `marker-pdf` (bundles Surya OCR) | latest |
| DOCX ingestion | `docx2python` | `>=3.0` |
| LLM client | `anthropic` official SDK | latest |
| Structured extraction | `instructor` | latest |
| Schema validation | `pydantic` | `>=2.0` |
| Offline OCR fallback | `pytesseract` + Tesseract 5.5 binary | bundled |
| Image handling | `Pillow` | latest |
| Secret storage | `keyring` | latest |
| Templating (Markdown export) | `jinja2` | latest |
| Packaging | `PyInstaller 6.x` + Inno Setup | latest |

**Dependencies Note**: The application includes a fallback mode for systems without NVIDIA GPUs. `marker-pdf` (Surya) is used when CUDA is available; otherwise, the app defaults to `pytesseract` for OCR.

**Python version**: 3.12 (required by marker-pdf).

Install command:
```
pip install pyside6 pymupdf pymupdf4llm marker-pdf docx2python \
            anthropic instructor pydantic pillow pytesseract jinja2 keyring
```

Tesseract binary ships **separately** inside the PyInstaller bundle at `./tesseract/tesseract.exe`. At runtime, detect the frozen path and set `pytesseract.pytesseract.tesseract_cmd` accordingly.

For local Windows setup, see [docs/windows-tesseract-setup.md](docs/windows-tesseract-setup.md).

---

## 2. Data Model

The canonical spell content uses the following Pydantic v2 model. Session storage and UI state wrap this model inside `SpellRecord` and `SessionState`, but `Spell` remains the canonical schema for extracted spell content, validation, and export.

### 2.1 Design rules (match the main application's spell schema)

| Rule | Detail |
|---|---|
| **Class list** | Each spell belongs to a `class_list`: `Wizard` or `Priest`. |
| **Tradition** | Derived automatically from `class_list`: Wizard → `Arcane`, Priest → `Divine`. Implemented as a `@computed_field` — not stored or extracted, but present in serialized output. |
| **School** | A list of one or more school names (strings). `SpellSchool` enum values are the canonical set; custom values are accepted but flagged for review. Wizard spells always populate `school`. Priest spells also list schools for reference purposes (e.g. determining spell-resistance interactions). |
| **Sphere** | Priest spells populate `sphere` with one or more sphere names (strings). `PriestSphere` enum values are the canonical set; custom values are accepted but flagged for review. Wizard spells leave `sphere` as `None`. A `model_validator` enforces this. |
| **Wizard level** | Integer `0`–`9`. Cantrips are stored as `0`. If the source text says `"Cantrip"`, normalise to `0` during extraction. |
| **Priest level** | Integer `1`–`7`. Quest spells are stored as `8`. If the source text says `"Quest"`, normalise to `8` during extraction. |
| **Combined schools** | Slash-separated schools such as `"Invocation/Evocation"` are valid single `SpellSchool` values — do not split them. |
| **Material components** | Not parsed into a separate field. Material component details remain in the spell `description`. The main application handles material-component parsing on import. |

### 2.2 Enumerations

```python
from pydantic import BaseModel, computed_field, field_validator, model_validator, ValidationInfo
from typing import Literal, Optional, Union
from enum import Enum
from app.utils.review_notes import strip_alt_tags


class SpellSchool(str, Enum):
    ABJURATION           = "Abjuration"
    AIR                  = "Air"
    ALCHEMY              = "Alchemy"
    ALTERATION           = "Alteration"
    ARTIFACE             = "Artifice"
    CALLING              = "Calling"
    CHARM                = "Charm"
    CONJURATION          = "Conjuration"
    CONJURATION_SUMMONING= "Conjuration/Summoning"
    CREATION             = "Creation"
    DIMENSION            = "Dimension"
    DIVINATION           = "Divination"
    EARTH                = "Earth"
    ENCHANTMENT          = "Enchantment"
    ENCHANTMENT_CHARM    = "Enchantment/Charm"
    EVOCATION            = "Evocation"
    FIRE                 = "Fire"
    FORCE                = "Force"
    GEOMETRY             = "Geometry"
    ILLUSION             = "Illusion"
    ILLUSION_PHANTASM    = "Illusion/Phantasm"
    INVOCATION           = "Invocation"
    INVOCATION_EVOCATION = "Invocation/Evocation"
    NECROMANCY           = "Necromancy"
    PHANTASM             = "Phantasm"
    SHADOW               = "Shadow"
    SUMMONING            = "Summoning"
    TELEPORTATION        = "Teleportation"
    TEMPORAL             = "Temporal"
    WATER                = "Water"
    WILD_MAGIC           = "Wild Magic"
    UNIVERSAL            = "Universal"


class PriestSphere(str, Enum):
    ALL              = "All"
    ANIMAL           = "Animal"
    ASTRAL           = "Astral"
    CHAOS            = "Chaos"
    CHARM            = "Charm"
    COMBAT           = "Combat"
    CREATION         = "Creation"
    DESERT           = "Desert"
    DESTINY          = "Destiny"
    DIVINATION       = "Divination"
    DROW             = "Drow"
    ELEMENTAL_AIR    = "Elemental Air"
    ELEMENTAL_EARTH  = "Elemental Earth"
    ELEMENTAL_FIRE   = "Elemental Fire"
    ELEMENTAL_WATER  = "Elemental Water"
    ELEMENTAL_RAIN   = "Elemental Rain"
    ELEMENTAL_SUN    = "Elemental Sun"
    EVIL             = "Evil"
    FATE             = "Fate"
    GOOD             = "Good"
    GUARDIAN         = "Guardian"
    HEALING          = "Healing"
    LAW              = "Law"
    MAGMA            = "Magma"
    NECROMANTIC      = "Necromantic"
    NUMBERS          = "Numbers"
    PLANT            = "Plant"
    PROTECTION       = "Protection"
    SILT             = "Silt"
    SUMMONING        = "Summoning"
    SUN              = "Sun"
    THOUGHT          = "Thought"
    TIME             = "Time"
    TRAVELERS        = "Travelers"
    WAR              = "War"
    WEATHER          = "Weather"


# Note: These Enums serve as reference catalogs of canonical values.
# The model fields use `list[str]` so freeform values are accepted.
# Unknown values trigger a review flag, not a validation error.
# The AppConfig stores `custom_schools` and `custom_spheres` lists
# to remember user-accepted extensions across sessions.


class ClassList(str, Enum):
    WIZARD  = "Wizard"
    PRIEST  = "Priest"


class Tradition(str, Enum):
    ARCANE = "Arcane"
    DIVINE = "Divine"


class Component(str, Enum):
    V = "V"
    S = "S"
    M = "M"
```

### 2.3 Spell model

```python
# SpellLevel: int for normal spells; see level rules in §2.1
# Wizard: 0 (Cantrip) through 9
# Priest: 1 through 7, plus 8 (Quest spell)
SpellLevel = int


class Spell(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────────
    name: str
    class_list: ClassList
    level: SpellLevel

    # Tradition is derived from class_list (Wizard → Arcane, Priest → Divine)
    @computed_field
    @property
    def tradition(self) -> Tradition:
        return Tradition.ARCANE if self.class_list == ClassList.WIZARD else Tradition.DIVINE

    # School is always populated (list of one or more); sphere is Priest-only (list of one or more)
    # Values are strings — SpellSchool/PriestSphere enums are canonical but freeform is accepted
    school: list[str]                        # one or more schools; both Wizard and Priest spells list schools
    sphere: Optional[list[str]] = None       # Priest spells only; one or more spheres

    # ── Stat block fields ─────────────────────────────────────────────────
    range: str                       # e.g. "0", "Touch", "30 yds", "10 yds/level", "Special"
    components: list[Component]
    duration: str                    # e.g. "1 rd/level", "Permanent", "Special"
    casting_time: str                # e.g. "1", "3", "1 rd", "1 turn", "Special"
    area_of_effect: str              # e.g. "One creature", "30-ft. radius", "Special"
    saving_throw: str                # e.g. "None", "Neg.", "½", "Special"

    # ── Description ───────────────────────────────────────────────────────
    description: str                 # full spell description, plain text (material components are described here)
    reversible: bool = False         # True if spell has a reversed form

    # ── Source tracking ───────────────────────────────────────────────────
    source_document: str             # e.g. "Player's Handbook", "Tome of Magic"
    source_page: Optional[int] = None  # **book** page number (not raw PDF page); offset applied during extraction; must be >= 1 before Accept/export

    # ── Quality metadata (not exported) ───────────────────────────────────
    confidence: float = 1.0          # 0.0–1.0; populated by extraction pipeline
    needs_review: bool = False
    review_notes: Optional[str] = None  # freeform notes plus optional ALT[field]=value lines for merge candidates
    extraction_start_line: int = -1  # markdown line index for UI highlighting
    extraction_end_line: int = -1    # markdown line index for UI highlighting

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator("level", mode="before")
    @classmethod
    def normalise_level(cls, v):
        """Accept 'Cantrip' → 0 and 'Quest' → 8 from raw extraction output."""
        if isinstance(v, str):
            if v.strip().lower() == "cantrip":
                return 0
            if v.strip().lower() == "quest":
                return 8
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"Cannot parse level: {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError("Confidence must be between 0 and 1")
        return v

    @model_validator(mode="after")
    def validate_school_sphere(self) -> "Spell":
        """Enforce that all spells have at least one school, and only Priest spells have sphere."""
        if not self.school:
            raise ValueError("All spells must have at least one school.")
        if self.class_list == ClassList.WIZARD and self.sphere is not None:
            raise ValueError("Wizard spells must not have a sphere.")
        if self.class_list == ClassList.PRIEST and (self.sphere is None or len(self.sphere) == 0):
            raise ValueError("Priest spells must have at least one sphere.")
        return self

    @model_validator(mode="after")
    def flag_unknown_school_sphere(self, info: ValidationInfo) -> "Spell":
        """Flag spells with non-canonical school or sphere values for review."""
        context = info.context or {}
        custom_schools = set(context.get("custom_schools", []))
        custom_spheres = set(context.get("custom_spheres", []))

        known_schools = {e.value for e in SpellSchool} | custom_schools
        known_spheres = {e.value for e in PriestSphere} | custom_spheres
        unknown_schools = [s for s in self.school if s not in known_schools]
        unknown_spheres = [s for s in (self.sphere or []) if s not in known_spheres]
        if unknown_schools or unknown_spheres:
            self.needs_review = True
            parts = []
            if unknown_schools:
                parts.append(f"Unknown school(s): {', '.join(unknown_schools)}")
            if unknown_spheres:
                parts.append(f"Unknown sphere(s): {', '.join(unknown_spheres)}")
            self.review_notes = (self.review_notes or "") + "; ".join(parts) + ". "
        return self

    @model_validator(mode="after")
    def validate_level_range_by_type(self) -> "Spell":
        """Enforce per-caster level ranges: Wizard 0–9, Priest 1–8."""
        if self.class_list == ClassList.WIZARD and not (0 <= self.level <= 9):
            raise ValueError(f"Wizard spell level must be 0–9, got {self.level}")
        if self.class_list == ClassList.PRIEST and not (1 <= self.level <= 8):
            raise ValueError(f"Priest spell level must be 1–8 (8 = Quest), got {self.level}")
        return self
```

### 2.4 Lax extraction model

Instructor targets a `LaxSpell` model during Stage 2 extraction. Every field is optional, but list, integer, float, and bool fields keep their natural types so partially valid LLM output can still be captured without crashing the call.

```python
class LaxSpell(BaseModel):
    """All-optional mirror of Spell used as the Instructor extraction target.
    Ensures partial LLM output is always captured for human review."""

    name: Optional[str] = None
    class_list: Optional[str] = None
    level: Optional[str] = None
    school: Optional[list[str]] = None
    sphere: Optional[list[str]] = None
    range: Optional[str] = None
    components: Optional[list[str]] = None
    duration: Optional[str] = None
    casting_time: Optional[str] = None
    area_of_effect: Optional[str] = None
    saving_throw: Optional[str] = None
    description: Optional[str] = None
    reversible: Optional[bool] = None
    source_document: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    needs_review: Optional[bool] = None
    review_notes: Optional[str] = None
    extraction_start_line: Optional[int] = None
    extraction_end_line: Optional[int] = None
```

**Conversion flow** (`LaxSpell → Spell`):

1. Instructor extracts into `LaxSpell` (retries up to 3 times on schema errors).
2. `LaxSpell.to_spell()` attempts `Spell.model_validate(self.model_dump(exclude_none=True))`.
3. **Validation succeeds** → returns a strict `Spell` object, routed to §4.4 post-extraction logic.
4. **Validation fails** → constructs a best-effort `Spell` with:
   - `confidence = 0.0`
   - `needs_review = True`
   - `review_notes` populated with the Pydantic `ValidationError` messages
   - All parseable fields carried over; unparseable fields filled with sensible defaults:
     - `school` → `["Unknown"]`, `sphere` → `["Unknown"]` (Priest) or `None` (Wizard)
     - String fields → `""`, booleans → `False`, `class_list` → `ClassList.WIZARD`
   - Routed directly to the review queue so the user can fix fields in the Review Panel.

This ensures that even after 3 failed Instructor retries, the user always gets **something** to work with rather than a silent data loss.

### 2.5 Extraction output hint for the LLM

Include this in the Stage 2 extraction system prompt so Claude knows how to handle these rules:

```
Level normalisation:
- If the level is missing from the stat block (common in the Player's Handbook), infer the level and class list from the `<context_heading>` XML tag provided in the prompt.
- If the source text shows "Cantrip" for a Wizard spell, output level: 0
- If the source text shows "Quest" for a Priest spell, output level: 8
- Otherwise output level as an integer

Class list:
- Set "class_list" to "Wizard" or "Priest" based on the source
- Do NOT output a "tradition" field — it is computed automatically from class_list

School and Sphere:
- "school" is a list of one or more schools — a spell can belong to multiple schools
- Always populate "school" for both Wizard and Priest spells
- "sphere" is a list of one or more spheres — a Priest spell can belong to multiple spheres
- Populate "sphere" only for Priest spells; leave "sphere" null for Wizard spells
- Combined schools (e.g. "Invocation/Evocation") are a single valid school value — do not split

Material components:
- Do NOT parse material components into a separate field
- Material component details should remain in the spell description text

Valid wizard schools: Abjuration, Air, Alchemy, Alteration, Artifice, Calling, Charm,
  Conjuration, Conjuration/Summoning, Creation, Dimension, Divination, Earth,
  Enchantment, Enchantment/Charm, Evocation, Fire, Force, Geometry, Illusion,
  Illusion/Phantasm, Invocation, Invocation/Evocation, Necromancy, Phantasm,
  Shadow, Summoning, Teleportation, Temporal, Water, Wild Magic, Universal

Valid priest spheres: All, Animal, Astral, Chaos, Charm, Combat, Creation, Desert,
  Destiny, Divination, Drow, Elemental Air, Elemental Earth, Elemental Fire,
  Elemental Water, Elemental Rain, Elemental Sun, Evil, Fate, Good, Guardian,
  Healing, Law, Magma, Necromantic, Numbers, Plant, Protection, Silt, Summoning,
  Sun, Thought, Time, Travelers, War, Weather
```

**Serialization rules**:
- JSON export (schema **`version` `1.1`**) includes **`needs_review`** and **`review_notes`** on each spell object. It omits `confidence`, `extraction_start_line`, and `extraction_end_line`. The top-level object also includes provenance fields **`exported_at`** (ISO-8601 UTC) and **`spellscribe_version`** (application or build string).
- Markdown export renders each spell as a structured block (see §6.2). When `needs_review` is true or `review_notes` is non-empty, the template appends a **Review** subsection.
- The `sphere` key is omitted from Wizard spell JSON.
- Internal storage uses a versioned **`SessionState`** envelope keyed by source-file **SHA-256**. On Windows, progress auto-saves to **`%APPDATA%\SpellScribe\session.json`** (alongside `config.json`). The session stores the full `CoordinateAwareTextMap`, ordered `SpellRecord` items, and one optional draft per record, so pending discoveries, extracted spells, highlights, and in-progress edits restore instantly without re-ingestion.
- Each `SpellRecord` has an immutable `spell_id`, a `status` (`pending_extraction`, `needs_review`, or `confirmed`), immutable extraction order, mutable per-section display order, boundary metadata, one optional committed `Spell`, and one optional draft `Spell`.
- **Session envelope metadata:** Persist **`source_sha256_hex`** (lower-case file digest) and **`last_open_path`** (display-only path for title/dialogs; not an identity key). Refresh `last_open_path` on every successful auto-save.
- **Restore by hash on Open:** If in-memory unsaved state is not for a *different* SHA, and the opened file hash matches `source_sha256_hex` in `session.json` with a complete `CoordinateAwareTextMap`, load that session immediately (no re-ingestion). Update `last_open_path` to the newly chosen path; rename/move does not invalidate the session.
- **Single session at a time:** Only one document extraction state is active. Opening a new file while a session exists prompts: *"You have unsaved work on [filename]. Export first, discard, or cancel?"* **except** when the new file has the same SHA-256 as the active session document; in that case, treat it as the same document, keep in-memory state, and only refresh `last_open_path`. The session clears only when the user explicitly discards it or confirms opening a different-SHA file. Export does **not** auto-clear session state.
- **Session load failure policy:** If `session.json` is corrupt or fails schema validation, rename it to `session.json.bad.<UTC-timestamp>`, show one non-blocking warning, and continue with empty in-memory state.
- **Session auto-save cadence:** Maintain a dirty flag and debounce writes to at most once every **2 seconds** while dirty. Force immediate checkpoints on spell extracted, page completed, cancel requested, app close, and confirmed file-switch action.
- **Session write durability:** Use atomic replace: write `session.json.tmp`, flush + fsync, then `os.replace(tmp, session.json)` to avoid half-written sessions on crash/power loss.

### 2.6 Coordinate-aware text mapping

Every ingestion method (§4.1) returns a `CoordinateAwareTextMap` that links each line of extracted Markdown back to its physical location in the source document. This structure drives the Document Panel highlights (§5.2), the spanning indicator (§5.3), and the "Go to Start / Go to End" navigation (§5.4).

```python
from dataclasses import dataclass


@dataclass
class TextRegion:
    """A physical region in the source document corresponding to a line of Markdown."""
    page: int                                         # 0-indexed PDF page; -1 for DOCX
    bbox: tuple[float, float, float, float] | None    # (x0, y0, x1, y1) in PDF points; None for DOCX
    char_offset: tuple[int, int] | None               # (start, end) character range in DOCX text; None for PDF


@dataclass
class CoordinateAwareTextMap:
    """Maps extracted Markdown lines to their source locations."""
    lines: list[tuple[str, TextRegion]]   # (markdown_line, region)

    def regions_for_range(self, start_line: int, end_line: int) -> list[TextRegion]:
        """Return all TextRegions for the given Markdown line range (used by UI highlight)."""
        return [region for _, region in self.lines[start_line:end_line]]

    def page_span(self, start_line: int, end_line: int) -> tuple[int, int]:
        """Return (first_page, last_page) for a spell's line range (used by spanning indicator)."""
        pages = {region.page for _, region in self.lines[start_line:end_line] if region.page >= 0}
        return (min(pages), max(pages)) if pages else (-1, -1)
```

**Per-ingestion behaviour**:

| Ingestion path | `bbox` | `char_offset` | Notes |
|---|---|---|---|
| PyMuPDF4LLM (digital PDF) | Populated via `page.get_text("dict")` cross-reference | `None` | Markdown line → text block bbox lookup |
| marker-pdf (scanned PDF) | Populated from Surya's OCR bounding boxes | `None` | Surya returns per-line coordinates natively |
| pytesseract (fallback OCR) | Populated from Tesseract's `image_to_data()` output | `None` | Row-level bounding boxes |
| docx2python (DOCX) | `None` | Populated by tracking character offsets during conversion | UI uses `QTextCursor` with offsets instead of graphical overlay |

**Session persistence note**: The `CoordinateAwareTextMap` must be serialized in full to `session.json`. Because bounding boxes for scanned PDFs are deeply coupled with the initial ingestion pass (e.g. Surya), saving them directly makes session recovery instantaneous and skips all heavy reprocessing.

### 2.7 Session state and record model

The app stores document-level state and record-level UI state separately from the canonical `Spell` payload. This keeps pending discoveries, draft edits, and confirmed spells in one consistent model.

```python
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class SpellRecordStatus(str, Enum):
  PENDING_EXTRACTION = "pending_extraction"
  NEEDS_REVIEW = "needs_review"
  CONFIRMED = "confirmed"


class SpellRecord(BaseModel):
  spell_id: str
  status: SpellRecordStatus
  extraction_order: int
  section_order: int                  # order within the current UI section
  boundary_start_line: int
  boundary_end_line: int = -1         # -1 until the next start or EOF closes the span
  context_heading: Optional[str] = None
  manual_source_page_override: bool = False
  canonical_spell: Optional[Spell] = None
  draft_spell: Optional[Spell] = None
  draft_dirty: bool = False


class SessionState(BaseModel):
  version: str = "1"
  source_sha256_hex: str
  last_open_path: str
  coordinate_map: CoordinateAwareTextMap
  records: list[SpellRecord]
  selected_spell_id: Optional[str] = None
```

- `status` drives the three list sections: `Pending Extraction`, `Needs Review`, and `Confirmed`.
- `draft_spell` stores one autosaved draft per record. UI edits target `draft_spell`, not `canonical_spell`.
- `manual_source_page_override` protects per-spell page edits when the document-level page offset changes.
- Export reads only committed `canonical_spell` values from `needs_review` and `confirmed` records. `pending_extraction` records and dirty drafts never export.

---

## 3. Application Architecture

```
SpellScribe/
├── main.py                  # Entry point; launches QApplication
├── app/
│   ├── __init__.py
│   ├── config.py            # AppConfig dataclass (API key, confidence threshold, paths)
│   ├── models.py            # Spell, LaxSpell, TextRegion, CoordinateAwareTextMap (§2)
│   ├── session.py           # SessionState, SpellRecord, autosave/load logic
│   ├── utils/
│   │   ├── __init__.py
│   │   └── review_notes.py  # parse_alt_tags(), upsert_alt_tag(), strip_alt_tags()
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── detector.py      # is_scanned_pdf(), detect_spell_boundaries()
│   │   ├── ingestion.py     # pdf_to_markdown(), docx_to_text(), route_document()
│   │   ├── extraction.py    # extract_spells_from_page(), extract_single_spell()
│   │   └── export.py        # to_json(), to_markdown()
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py   # QMainWindow shell; owns toolbar and three-panel layout
│       ├── document_panel.py  # Left: PDF/DOCX viewer
│       ├── spell_list_panel.py # Centre: three-section QListWidget of record states
│       └── review_panel.py  # Right: draft-backed form or pending status view
├── resources/
│   ├── few_shot_examples.json   # 4–6 ground-truth spell extraction examples
│   └── templates/
│       └── spell.md.j2          # Jinja2 template for Markdown export
├── tesseract/               # Bundled Tesseract binary (Windows)
│   ├── tesseract.exe
│   └── tessdata/eng.traineddata
├── requirements.txt
└── build/
  ├── spell_scribe_std.spec # Standard PyInstaller spec (CPU/Tesseract)
  ├── spell_scribe_pro.spec # Pro PyInstaller spec (Marker/CUDA)
    └── installer.iss        # Inno Setup script
```

---

## 4. Extraction Pipeline (the core logic)

### 4.1 Document routing

```python
def route_document(path: str) -> CoordinateAwareTextMap:
    """
    Accept a .pdf or .docx file.
    Return a CoordinateAwareTextMap linking Markdown lines to their
    physical source locations (see §2.6).
    """
```

- If `.docx`: use `docx2python(path, html=True)` to get run-level HTML tags.
  Convert to Markdown preserving `**bold**` and `*italic*` for field labels.
  For **`source_page`** on DOCX: auto-fill **only** when the conversion stack yields a **non-empty, internally consistent** page sequence; otherwise leave **`source_page` null** until the user sets it manually in the Review panel. That spell cannot be accepted into Confirmed (or included in Confirmed-only export) until `source_page` is populated.
- If `.pdf`:
  - Open with `fitz.open(path)`.
  - For each page, compute `text_ratio = len(page.get_text()) / page.rect.area`.
  - If `text_ratio < 0.005` → mark as **scanned** (note: do NOT use image coverage percentages or textured background images will trigger false-positives on digital PDFs; users can apply **Force OCR** for the current document if an invisible Acrobat text layer is unusable). **Force OCR** is persisted in `AppConfig` keyed by the **SHA-256 hash of the file bytes** (same identity key as the session): if the file content changes, the override does not carry over until set again.
  - Digital pages: convert with `pymupdf4llm.to_markdown(doc, pages=[n])`.
  - Scanned pages: pass through `marker-pdf` (if GPU available) or `pytesseract` to get layout-aware Markdown.
- **Coordination**: Every ingestion method must return a `CoordinateAwareTextMap` (see §2.6). This object links every line of Markdown back to its physical source location via `TextRegion` objects (PDF: `(x0, y0, x1, y1)` bounding box; DOCX: `(start, end)` character offsets).
  - **PDF Highlights**: The UI highlights the union of all rectangles corresponding to the lines of the spell block.
  - **DOCX Highlights**: The UI uses `QTextCursor` to select and highlight the text range in the read-only viewer.

### 4.2 Spell boundary detection (Stage 1 LLM call)

For each page of Markdown, send a **boundary detection** request using the model specified by `AppConfig.stage1_model` (default: Claude Haiku 4.5 — a cheap, fast classification task).

**System prompt** (enable [Anthropic prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) via `cache_control: {"type": "ephemeral"}` — reused across all pages):
```
You are a parser for Advanced Dungeons & Dragons 2nd Edition spell books.
Your task is to identify where each spell begins on a page, and what the current chapter/section heading is (e.g. "First-Level Spells" or "Third-Level Priest Spells").
Return ONLY a JSON block. No prose, no markdown fences.
```

**User message**:
```xml
<page_number>{n}</page_number>
<page_text>
{numbered_markdown_text}
</page_text>

Return a JSON object in this exact format:
{
  "active_heading": "The current section/level heading affecting these spells (or null if none exists on this page)",
  "end_of_spells_section": false, // set to true if the page clearly transitions OUT of a spell listing into another major topic (e.g., gap between Wizard and Priest chapters, or End of Book)
  "spells": [
    {"spell_name": "...", "start_line": "042"}
  ]
}
If no spells are found, return the heading (if one exists) and an empty array.
```

**Implementation Note:** To prevent LLM counting hallucinations, the script MUST preprocess the Markdown string and prefix every line with its absolute 0-indexed line number (e.g. `042: **Magic Missile** (Evocation)`). The AI will then return the exact parsed prefix ID rather than attempting to count newlines. Parse the response with `json.loads`. The `ExtractionWorker` maintains the `active_heading` sequentially. If a page returns a non-null `active_heading`, update the worker's running state. If `end_of_spells_section` is true, the worker immediately closes any currently pending spell span and **stops Stage 1 discovery for the file immediately** (ignore remaining pages and empty-page cutoff). This state is passed to Stage 2 to provide missing level/class context. Stage 1 also tracks consecutive "empty" pages (`active_heading == null` and no spells) **after at least one spell has been found** and consults `AppConfig.stage1_empty_page_cutoff`: if set to a positive integer `N`, early-stop discovery when the empty streak reaches `N`; if set to `0`, scan to end-of-file with no early-stop. Any non-null heading or any spell start resets the empty-page streak counter.

### 4.3 Per-spell extraction (Stage 2 LLM call)

For each detected spell, crop the relevant lines from the Markdown and send an **extraction** request using the model specified by `AppConfig.stage2_model` (default: Claude Sonnet 4 — balances extraction quality against cost).

Use **Instructor** with `mode=instructor.Mode.TOOLS` and the `LaxSpell` Pydantic model (see §2.4).

**System prompt** (enable Anthropic prompt caching — this prompt including few-shot examples is reused for every spell extraction call, saving ~90% on input tokens after the first call):
```
You are an expert parser for Advanced Dungeons & Dragons 2nd Edition spell stat blocks.
Extract all fields from the spell text provided. Return a single Spell object.

AD&D 2e spell blocks have this structure:
- Spell Name (bold, at the top)
- School/Sphere line: "School: Alteration" or "Sphere: Healing"
  A spell can list multiple schools, e.g. "(Abjuration, Evocation)" — capture all of them.
- Level line: "Level: 3" or "Wizard 3" or "Priest 2"
- Range, Components, Duration, Casting Time, Area of Effect, Saving Throw
  (each on its own line, label in bold or followed by a colon)
- A blank line, then the full description paragraph(s)

Rules:
- Set "class_list" to "Wizard" or "Priest". Do NOT output "tradition" — it is computed automatically.
- A "Sphere:" label in the source text indicates a Priest spell — populate the `sphere` field.
  Priest spells also list one or more schools for reference (e.g. spell resistance interactions).
- "school" is always a list, even if there is only one school.
- "sphere" is always a list, even if there is only one sphere.
- If the spell is reversible, set reversible=true.
- Do NOT extract material components into a separate field. Leave them in the description.
- Set confidence to a float between 0.0 and 1.0 reflecting your certainty.
- Set needs_review=true if any field is ambiguous or you are unsure.
- source_document and source_page are provided to you; copy them verbatim.

<few_shot_examples>
{few_shot_json}
</few_shot_examples>
```

**User message**:
```xml
<source_document>{doc_name}</source_document>
<source_page>{page_num}</source_page>          <!-- book page = pdf_page + offset -->
<context_heading>{active_heading}</context_heading> <!-- from Stage 1 sequential state -->
<spell_text>
{cropped_markdown}
</spell_text>
```

- **Stage commands**:
  - **Detect Spells** runs Stage 1 only. It creates or updates `Pending Extraction` `SpellRecord` items as spell boundaries become final.
  - **Extract Selected** runs Stage 2 only for selected `Pending Extraction` records.
  - **Extract All Pending** runs Stage 2 for all current `Pending Extraction` records.
- **Sequential Discovery, Parallel Extraction**:
  - **Stage 1 (Discovery)**: A worker processes pages sequentially to build a manifest of spell boundaries. It only considers a spell "Ready" once the *next* spell's start point is found (ensuring page-spanning descriptions are captured) or the file ends. At that moment, the app writes or updates a `SpellRecord` with `status="pending_extraction"` and the closed boundary span.
  - **Stage 2 (Extraction)**: When the user starts an extraction command, the selected or all pending records are pushed to a parallel queue (capped at `AppConfig.max_concurrent_extractions`). Rely on the Anthropic SDK's native `max_retries` configuration to handle rate limits automatically rather than writing custom backoff logic.
- **Lax Model**: Extraction first uses a `LaxSpell` model where all fields are optional values. This ensures Claude can return partial or malformed data for manual review rather than failing the entire call on a minor schema violation.
- On `ValidationError`, Instructor will automatically retry up to 3 times feeding the error back into the conversation.

### 4.4 Post-extraction routing

```python
# confidence_threshold is configured in AppConfig (e.g., 0.85)

for record in pending_records_to_extract:
    spell = extract_spell(record)
    record.canonical_spell = spell
    record.draft_spell = None
    if spell.confidence < config.confidence_threshold or spell.needs_review:
        spell.needs_review = True
        record.status = SpellRecordStatus.NEEDS_REVIEW
    else:
        record.status = SpellRecordStatus.CONFIRMED
```

---

## 5. User Interface

### 5.1 Main window layout

Three-panel layout using `QSplitter`:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Toolbar: [Open File] [Detect Spells] [Extract Selected] [Extract All Pending] │
│           [Export] [Settings]                         [Progress bar] │
├──────────────────┬───────────────────┬────────────────────────────┤
│  Document Panel  │  Spell List Panel │  Review / Status Panel     │
│  (left, 30%)     │  (centre, 25%)    │  (right, 45%)              │
│                  │                   │                            │
│  PDF page image  │  Confirmed ✓      │  Draft-backed editor       │
│  or DOCX text    │  ────────────     │  or pending status view    │
│  rendered with   │  > Magic Missile  │                            │
│  highlighted     │  > Fireball       │                            │
│  bounding box    │  > Sleep          │                            │
│  for selected    │                   │                            │
│  record          │  Needs Review ⚠   │                            │
│                  │  ────────────     │                            │
│                  │  > Bigby's Hand   │                            │
│                  │  > Wraithform     │                            │
│                  │                   │                            │
│                  │  Pending Extraction│                            │
│                  │  ───────────────  │                            │
│                  │  > Flame Walk     │                            │
│                  │  > Sol's Searing Orb │                         │
└──────────────────┴───────────────────┴────────────────────────────┘
│  Status bar: "OCR Mode: Standard (CPU) | Confirmed 35 | Review 12 | Pending 5 | Page 12/34" │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Document Panel (`document_panel.py`)

- For PDFs: render current page as a `QPixmap` using PyMuPDF's `page.get_pixmap()`. Display in a `QLabel` inside a `QScrollArea`. Highlight the bounding box of the currently-selected record with a semi-transparent yellow `QPainter` overlay.
- For DOCX: render the raw Markdown text in a `QPlainTextEdit` (read-only) with syntax highlighting for field labels (bold patterns → green, spell names → blue).
- Navigation arrows to page forward/back.

### 5.3 Spell List Panel (`spell_list_panel.py`)

- `QListWidget` with three sections separated by visual dividers: **Confirmed** (green checkmark icon), **Needs Review** (amber warning icon), and **Pending Extraction** (gray queue icon).
- **Multi-Selection**: Supports SHIFT/CTRL selection for bulk right-click actions (Move to Confirmed, Delete).
- **Audit Sorting**: Users can sort the Confirmed list by confidence (ascending) to audit "Weak Greens." This is a temporary audit view and does not rewrite the persisted Confirmed-section order.
- **Spanning Indicator**: Spells covering >1 page show a "two-page" icon.
- **Duplicate Indicator**: Records with a naming conflict against the Confirmed list show a red overlap icon.
- Single-click selects a record and updates the right panel and Document Panel highlight. Pending records open a read-only status view. Extracted records open a draft-backed edit form.
- Right-click context menu adapts to record status:
  - **Pending Extraction**: **Extract**, **Delete**
  - **Needs Review**: **Move to Confirmed**, **Delete**, **Re-extract**
  - **Confirmed**: **Delete**, **Re-extract**
- Bulk **Move to Confirmed** processes only selected `Needs Review` records whose committed canonical spell already passes strict validation and duplicate checks. The UI keeps skipped records in place and shows a summary.
- **Delete** permanently removes selected `SpellRecord` items and any associated drafts from `SessionState` after confirmation.
- Shows spell name + level label + school/sphere as a two-line list item. Level label reads "Cantrip" when level = 0 (Wizard) or "Quest" when level = 8 (Priest); otherwise shows the integer. Schools and spheres are displayed comma-separated when multiple.

### 5.4 Review / Edit Panel (`review_panel.py`)

Displays a panel bound to the currently selected `SpellRecord`.

- `Pending Extraction` records show a read-only status view with boundary lines, context heading, and actions to start extraction or delete the record.
- `Needs Review` and `Confirmed` records show a draft-backed edit form. All visible spell fields edit `draft_spell`, not `canonical_spell`.

For `Needs Review` and `Confirmed` records, the layout is:

```
Spell Name:     [_______________________________]
Class List:     ( Wizard )  ( Priest )
Tradition:      [label: ARCANE/DIVINE — computed from Class List, read-only]
School:         [editable multi-select — SpellSchool values + freeform]   ← always visible; one or more
Sphere:         [editable multi-select — PriestSphere values + freeform]   ← visible only when Priest; one or more
Level:          [spinbox 0–9]  [label: "Cantrip" if 0+Wizard | "Quest" if 8+Priest]
Range:          [________________________]
Components:     [x] V  [x] S  [ ] M
Duration:       [________________________]
Casting Time:   [________________________]
Area of Effect: [________________________]
Saving Throw:   [________________________]
Reversible:     [ ] Yes
Source Doc:     [________________________]
Source Page:    [spinbox] (Book p.131) | [label: PDF p.140]   ← book page is editable; PDF page derived from offset
                [Go to Start] [Go to End]   ← Only for page-spanning spells

Description:
[_____________________________________________]
[_____________________________________________]   (QPlainTextEdit, 8 rows)

Review Notes:   [________________________]
Confidence:     0.73  ⚠ Needs review

[ Accept & Move to Confirmed ]   [ Save Changes ]   [ Discard Draft ]   [ Delete ]   [ Re-extract ]
```

- **Accept & Move to Confirmed** appears only for `Needs Review` records. **Save Changes** appears only for `Confirmed` records.
- One autosaved draft exists per record. Switching selection preserves the draft and restores it when the record is reselected.
- When **Class List** is toggled, the Tradition label updates automatically (Wizard→ARCANE, Priest→DIVINE), the Sphere row visibility toggles, and the hidden field is cleared on the draft model.
- The School and Sphere multi-selects are editable combo-lists: canonical enum values are suggested, and users can type freeform values. Non-canonical values display with an amber indicator. Add values to `AppConfig.custom_schools` / `custom_spheres` **only after successful Accept or Save Changes**. Discard Draft, Delete, and Re-extract never learn values.
- The level spinbox range adjusts: Wizard allows 0–9; Priest allows 1–8.
- **Real-time Validation**: On every edit, the form runs `Spell.model_validate()` in strict mode against the current draft.
- **Guided UI**: Fields with validation errors are highlighted with **red borders** and a descriptive tooltip (from Pydantic's `loc` and `msg`).
- **Conflict Management**: Clicking **Accept** checks for `name` + `class_list` duplicates in Confirmed. Duplicate matching uses normalized `name` (`name.strip().casefold()`) plus exact `class_list`. On conflict, show **Over-write**, **Keep Both**, or **Skip**:
  - **Keep Both:** Keep both records in memory, but keep **Accept** disabled until the incoming spell name is edited so no two Confirmed spells share the same normalized `(name, class_list)` key.
  - **Over-write:** Update the existing Confirmed record in place, preserving its record identity and display position.
  - **Skip:** Abort the accept action.
- For `Confirmed` records, duplicate conflicts on **Save Changes** are inline validation errors. The form disables **Save Changes** until the normalized `(name, class_list)` key is unique.
- **Guided Re-extract**: Clicking **Re-extract** prompts for a "Focus area" string (e.g. "Duration is wrong"), injected into Stage 2 as `<user_correction>`. To reduce Stage 1 truncation risk, re-extract expands the `CoordinateAwareTextMap` slice by ±20 lines before sending to Stage 2. Apply a **field-aware merge** on return into the current draft only: update correction-targeted fields or clearly improved validated fields, and preserve unrelated user edits. If a returned value conflicts with a manual edit and improvement is not provable, keep the manual value and upsert exactly one machine-parseable alternative per field in `review_notes` as `ALT[field_name]=candidate text`.
- The **Accept** button stays disabled until all strict validation errors are resolved **and** `source_page` is a positive integer (`>= 1`).
- The **Save Changes** button uses the same validation gate and also requires that no duplicate-key conflict exists in Confirmed.
- **Discard Draft** deletes the autosaved draft for the selected record and reloads the committed canonical spell.
- On successful **Accept & Move to Confirmed**: commit the draft to `canonical_spell`, set `needs_review = False`, change the record status to `confirmed`, strip internal `ALT[...]` lines from `review_notes`, keep only human-facing note text unless manually cleared, normalize blank or whitespace-only `review_notes` to `None`, and clear the draft-dirty flag.
- On successful **Save Changes**: commit the draft to `canonical_spell`, keep the record status as `confirmed`, strip internal `ALT[...]` lines from `review_notes`, normalize blank or whitespace-only `review_notes` to `None`, and clear the draft-dirty flag.

### 5.5 Settings Dialog

Accessible from toolbar. Stores values in `AppConfig` which persists to **`%APPDATA%\SpellScribe\config.json`** (see §7).

```
API key source:         ( Environment variable ANTHROPIC_API_KEY ) ( Remember on this PC — Windows Credential Manager via keyring )  [ Advanced: store in config file ]
Anthropic API Key:       [_____________________________]  [Test]
Stage 1 Model:           [dropdown: claude-haiku-4-5-latest ▾]  (boundary detection)
Stage 2 Model:           [dropdown: claude-sonnet-4-latest ▾]   (spell extraction)
Empty-Page Cutoff:       [spinbox 0–200, default 10]             (Stage 1; 0 = scan to end-of-file)
Max Parallel Extractions:[spinbox 1–20, default 5]               (concurrent Stage 2 calls)
OCR Engine:              (Auto-detect) (Marker/GPU) (Tesseract/CPU)
Confidence Threshold:    [slider 0.5–1.0, default 0.85]
Default Export Directory:[_____________________________]  [Browse]
Tesseract Path:          [_____________________________]  (auto-detected)
Source Document Name:    [_____________________________]  (pre-filled for next import)
```

Model dropdowns offer `claude-haiku-4-5-latest`, `claude-sonnet-4-latest`, and `claude-opus-4-latest`. The user can trade cost for accuracy (Haiku ~$0.25/M tokens, Sonnet ~$3/M, Opus ~$15/M).

Credential-manager mode uses `keyring` with service name `SpellScribe` and account name `anthropic_api_key`.

### 5.6 Progress and threading

- All extraction runs on a `QThread` subclass (`ExtractionWorker`).
- Worker emits: `spell_discovered(SpellRecord)`, `spell_extracted(SpellRecord)`, `page_completed(int, int)`, `error(str)`, `finished()`.
- Main thread connects these signals to update the pending, review, and confirmed sections live as records change state.
- A `QProgressBar` in the toolbar shows page progress.
- A **Cancel** button appears while extraction is running and calls `worker.requestInterruption()`. **Cancelled runs keep partial progress**: any completed `Pending Extraction` records and finished Stage 2 records are written to the auto-saved session; only in-flight work is dropped.
- **Autosave execution detail:** Review-panel edits mark session dirty but do not force immediate disk writes; a 2-second debounce timer flushes changes. Checkpoint events (spell/page/cancel/close/file-switch confirm) bypass debounce and persist immediately.

---

## 6. Export

### 6.0 Export dialog (JSON and Markdown)

A **single export dialog** drives **JSON and/or Markdown** (user selects one or both output files in one flow). The following options apply **identically** to every selected format:

Export reads committed canonical `Spell` objects only. `Pending Extraction` records and dirty drafts are session-only state and never export.

- **Scope** (three modes; choice is remembered across sessions):
  - **Confirmed only** — spells in the Confirmed list; export order = **current persisted Confirmed-section order** (top to bottom, ignoring any temporary audit sort view).
  - **Needs Review only** — spells still in the Needs Review queue; export order = **current persisted Needs Review-section order** (top to bottom).
  - **Everything extracted** — union of the Confirmed and Needs Review lists only (**default** when the dialog is first opened or reset). `Pending Extraction` records are never included. **Merge order**: one combined list sorted by **`extraction_start_line`** ascending; spells with missing or **`-1`** `extraction_start_line` sort **after** all well-keyed spells, stable tie-break by **`name`** case-insensitive. Same ordering for Markdown export.
- **Dirty drafts warning**: Before export starts, if any record has a dirty draft, show a warning that uncommitted edits will not be included unless the user saves them first.
- **Clean export** (optional checkbox; **default off**): when enabled, include **only** spells with **`needs_review == false`**. When disabled, all spells in the chosen scope are included regardless of `needs_review` (but `needs_review` and `review_notes` are still written to JSON for downstream tooling).

### 6.1 JSON export

```python
from enum import Enum

class ExportScope(str, Enum):
    CONFIRMED_ONLY = "confirmed_only"
    NEEDS_REVIEW_ONLY = "needs_review_only"
    ALL = "all"


ALWAYS_EXCLUDE = {"confidence", "extraction_start_line", "extraction_end_line"}


def to_json(
    spells: list[Spell],
    path: str,
    *,
    clean_only: bool,
    exported_at: str,
    spellscribe_version: str,
) -> None:
    """
  Caller supplies committed canonical `Spell` objects already filtered to the chosen `ExportScope` (§6.0)
    and sorted per §6.0 (list order for single-bucket scopes; merged line order for ALL).
    Then optionally filter by clean_only (needs_review must be False).
    Omit: confidence, extraction_start_line, extraction_end_line.
    Include: needs_review, review_notes (after stripping internal ALT[...] lines).
    Omit: sphere for Wizard spells.
    """
    data = []
    for s in spells:
        if clean_only and s.needs_review:
            continue
        exclude = ALWAYS_EXCLUDE | (
            {"sphere"} if s.class_list == ClassList.WIZARD else set()
        )
        payload = s.model_dump(exclude=exclude)
        payload["review_notes"] = strip_alt_tags(payload.get("review_notes"))
        data.append(payload)
    envelope = {
        "version": "1.1",
        "exported_at": exported_at,
        "spellscribe_version": spellscribe_version,
        "spells": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, ensure_ascii=False)
```

Output structure (illustrative fragment):
```json
{
  "version": "1.1",
  "exported_at": "2026-04-19T12:34:56Z",
  "spellscribe_version": "1.0.0",
  "spells": [
    {
      "name": "Magic Missile",
      "class_list": "Wizard",
      "tradition": "Arcane",
      "school": ["Evocation"],
      "level": 1,
      "range": "60 yds + 10 yds/level",
      "components": ["V", "S"],
      "duration": "Instantaneous",
      "casting_time": "1",
      "area_of_effect": "1–5 targets",
      "saving_throw": "None",
      "description": "Use of the magic missile spell ...",
      "reversible": false,
      "source_document": "Player's Handbook",
      "source_page": 140,
      "needs_review": false,
      "review_notes": null
    },
    {
      "name": "Cure Light Wounds",
      "class_list": "Priest",
      "tradition": "Divine",
      "school": ["Necromancy"],
      "sphere": ["Healing"],
      "level": 1,
      "range": "Touch",
      "components": ["V", "S"],
      "duration": "Permanent",
      "casting_time": "5",
      "area_of_effect": "Creature touched",
      "saving_throw": "None",
      "description": "When casting this spell ...",
      "reversible": true,
      "source_document": "Player's Handbook",
      "source_page": 257,
      "needs_review": false,
      "review_notes": null
    }
  ]
}
```

### 6.2 Markdown export

Use **Jinja2** with the template at `resources/templates/spell.md.j2`. Apply the **same** `ExportScope`, **spell ordering** (§6.0), and `clean_only` filtering as §6.1 before rendering. Strip internal `ALT[...]` lines from `review_notes` before passing values to the template.

```jinja2
## {{ spell.name }}{% if spell.reversible %} *(Reversible)*{% endif %}

**School:** {{ spell.school | join(", ") }}{% if spell.sphere %} | **Sphere:** {{ spell.sphere | join(", ") }}{% endif %} | **Level:** {{ spell.class_list }} {{ spell.level }} | **Tradition:** {{ spell.tradition }}

| Field | Value |
|---|---|
| Range | {{ spell.range }} |
| Components | {{ spell.components | join(", ") }} |
| Duration | {{ spell.duration }} |
| Casting Time | {{ spell.casting_time }} |
| Area of Effect | {{ spell.area_of_effect }} |
| Saving Throw | {{ spell.saving_throw }} |

{{ spell.description }}

{% if spell.needs_review or spell.review_notes %}
### Review

{% if spell.needs_review %}**Needs review:** yes{% else %}**Needs review:** no{% endif %}

{% if spell.review_notes %}{{ spell.review_notes }}{% endif %}

{% endif %}

*Source: {{ spell.source_document }}{% if spell.source_page %}, p. {{ spell.source_page }}{% endif %}*

---
```

The export function concatenates all selected spells through this template (after the same scope/clean filters as JSON), using human-facing `review_notes` with `ALT[...]` metadata removed, and writes to a single `.md` file.

---

## 7. Configuration (`config.py`)

On **Windows**, all file-based persistent application data lives under **`%APPDATA%\SpellScribe\`** (create the directory on first run). This includes **`config.json`**, **`session.json`**, and any future sidecar files.

```python
from dataclasses import dataclass, field, fields
from pathlib import Path
import json, os


def spellscribe_data_dir() -> Path:
    """Return the SpellScribe data directory (Windows: %APPDATA%\\SpellScribe)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "SpellScribe"


CONFIG_PATH = spellscribe_data_dir() / "config.json"
CREDENTIAL_SERVICE_NAME = "SpellScribe"
CREDENTIAL_ACCOUNT_NAME = "anthropic_api_key"

@dataclass
class AppConfig:
    # API key: prefer ANTHROPIC_API_KEY in the environment. If the user enables
  # "Remember on this PC", default to Windows Credential Manager through
  # keyring; an advanced option may store plaintext in config (discouraged).
  # Never commit secrets.
    api_key_storage_mode: str = "env"  # "env" | "credential_manager" | "local_plaintext"
    api_key: str = ""  # used only for local_plaintext mode; empty otherwise
    stage1_model: str = "claude-haiku-4-5-latest"    # boundary detection (cheap, fast)
    stage2_model: str = "claude-sonnet-4-latest"     # spell extraction (quality/cost balance)
    stage1_empty_page_cutoff: int = 10               # Stage 1 early-stop after N empty pages; 0 = scan to EOF
    max_concurrent_extractions: int = 5              # parallel Stage 2 calls (1–20)
    confidence_threshold: float = 0.85
    export_directory: str = str(Path.home() / "Documents")
    tesseract_path: str = ""          # auto-detected if blank
    default_source_document: str = "Player's Handbook"
    last_import_directory: str = ""
    # "Learning" schema extensions
    custom_schools: list[str] = field(default_factory=list)
    custom_spheres: list[str] = field(default_factory=list)
    # Keys are lower-case SHA-256 hex digests of source file bytes (same as session key).
    # Values are integers such that book_page = pdf_page_index + offset.
    document_offsets: dict[str, int] = field(default_factory=dict)
    # When True for a given source SHA, force OCR for that PDF even if text_ratio suggests digital text.
    force_ocr_by_sha256: dict[str, bool] = field(default_factory=dict)

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.__dict__, f, indent=2)

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            # Filter unknown keys (forward-compat) and use defaults for missing keys (backward-compat)
            known_fields = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known_fields})
        return cls()
```

**Secrets:** Prefer **`ANTHROPIC_API_KEY`** in the environment. If the user opts in to **Remember on this PC**, the **default** storage backend is **Windows Credential Manager** through `keyring`. Store the key under service name **`SpellScribe`** and account name **`anthropic_api_key`**. An **advanced** setting allows plaintext in `config.json` for edge cases only. Document this in the README. Never commit keys to the repository.

**Migrating older configs:** If `document_offsets` was previously keyed by human `source_document` strings, migrate entries to **SHA-256 keys** the first time each file is opened (compute hash, remap offset, drop the legacy string key).

---

## 8. Few-Shot Examples File

`resources/few_shot_examples.json` must contain at least **4 examples** in the following format, drawn from real AD&D 2e spell blocks (use the PHB or Tome of Magic as sources):

```json
[
  {
    "input": "**Wish** (Conjuration/Summoning)\nLevel: 9\nRange: Unlimited\nComponents: V\nDuration: Special\nCasting Time: Special\nArea of Effect: Special\nSaving Throw: Special\n\nThe wish spell is a more potent version of a limited wish. If it is used to alter reality...",
    "output": {
      "name": "Wish",
      "class_list": "Wizard",
      "school": ["Conjuration/Summoning"],
      "level": 9,
      "range": "Special",
      "components": ["V"],
      "duration": "Special",
      "casting_time": "Special",
      "area_of_effect": "Special",
      "saving_throw": "Special",
      "description": "The wish spell is a more potent version of a limited wish. If it is used to alter reality...",
      "reversible": false,
      "source_document": "Player's Handbook",
      "source_page": 140,
      "confidence": 1.0,
      "needs_review": false
    }
  },
  {
    "input": "**Magic Missile** (Evocation)\nLevel: 1\nRange: 60 yds. + 10 yds./level\nComponents: V, S\nDuration: Instantaneous\nCasting Time: 1\nArea of Effect: 1-5 targets\nSaving Throw: None\n\nUse of the magic missile spell creates one...",
    "output": {
      "name": "Magic Missile",
      "class_list": "Wizard",
      "school": ["Evocation"],
      "level": 1,
      "range": "60 yds + 10 yds/level",
      "components": ["V", "S"],
      "duration": "Instantaneous",
      "casting_time": "1",
      "area_of_effect": "1–5 targets",
      "saving_throw": "None",
      "description": "Use of the magic missile spell creates one...",
      "reversible": false,
      "source_document": "Player's Handbook",
      "source_page": 140,
      "confidence": 1.0,
      "needs_review": false
    }
  },
  {
    "input": "**Alarm**\n (Abjuration, Evocation)\n(Geometry)\nLevel: 1\nRange: 10 yds. \n Components: V, S, M\nDuration: 4 hrs. + 1/2 hr./level \n Casting Time: 1 rd.\nArea of Effect: Up to 20-ft. cube \n Saving Throw: None\n\nWhen an alarm spell is cast, the wizard causes a selected area to react to the presence of any creature larger than a normal rat -- anything larger than about 1.2 cubic foot in volume or more than about three pounds in weight. The area of effect can be a portal, a section of floor, stairs, etc. As soon as any creature enters the warded area, touches it, or otherwise contacts it without speaking a password established by the caster, the alarm spell lets out a loud ringing that can be heard clearly within a 60-foot radius. (Reduce the radius by 10 feet for each interposing door and by 20 feet for each substantial interposing wall.) The sound lasts for one round and then ceases. Ethereal or astrally projected creatures do not trigger an alarm, but flying or levitating creatures, invisible creatures, or incorporeal or gaseous creatures do. The caster can dismiss the alarm with a single word. The material components of this spell are a tiny bell and a piece of very fine silver wire.",
    "output": {
      "name": "Alarm",
      "class_list": "Wizard",
      "school": ["Abjuration", "Evocation", "Geometry"],
      "level": 1,
      "range": "10 yds.",
      "components": ["V", "S", "M"],
      "duration": "4 hrs. + 1/2 hr./level",
      "casting_time": "1 rd.",
      "area_of_effect": "Up to 20-ft. cube",
      "saving_throw": "None",
      "description": "When an alarm spell is cast, the wizard causes a selected area to react to the presence of any creature larger than a normal rat -- anything larger than about 1.2 cubic foot in volume or more than about three pounds in weight. The area of effect can be a portal, a section of floor, stairs, etc. As soon as any creature enters the warded area, touches it, or otherwise contacts it without speaking a password established by the caster, the alarm spell lets out a loud ringing that can be heard clearly within a 60-foot radius. (Reduce the radius by 10 feet for each interposing door and by 20 feet for each substantial interposing wall.) The sound lasts for one round and then ceases. Ethereal or astrally projected creatures do not trigger an alarm, but flying or levitating creatures, invisible creatures, or incorporeal or gaseous creatures do. The caster can dismiss the alarm with a single word. The material components of this spell are a tiny bell and a piece of very fine silver wire.",
      "reversible": false,
      "source_document": "Wizards Spell Compendium",
      "source_page": 32,
      "confidence": 1.0,
      "needs_review": false
    }
  },
  {
    "input": "**Sanctuary**\n(Abjuration)\nSphere: Protection\nLevel: 1\nRange: Touch Components: V, S, M\nDuration: 2 rds. + 1 rd./level Casting Time: 4\nArea of Effect: 1 creature Saving Throw: None\n\nWhen the priest casts a sanctuary spell, any opponent attempting to strike or otherwise directly attack the protected creature must roll a saving throw vs. spell. If the saving throw is successful, the opponent can attack normally and is unaffected by that casting of the spell. If the saving throw is failed, the opponent loses track of and totally ignores the warded creature for the duration of the spell. Those not attempting to attack the subject remain unaffected. Note that this spell does not prevent the operation of area attacks (fireball, ice storm, etc.). While protected by this spell, the subject cannot take direct offensive action without breaking the spell, but may use nonattack spells or otherwise act in any way that does not violate the prohibition against offensive action. This allows a warded priest to heal wounds, for example, or to bless, perform an augury, chant, cast a light in the area (but not upon an opponent), and so on.\nThe components of the spell include the priest's holy symbol and a small silver mirror.",
    "output": {
      "name": "Sanctuary",
      "class_list": "Priest",
      "school": ["Abjuration"],
      "sphere": ["Protection"],
      "level": 1,
      "range": "Touch",
      "components": ["V", "S", "M"],
      "duration": "2 rds. + 1 rd./level",
      "casting_time": "4",
      "area_of_effect": "1 creature",
      "saving_throw": "None",
      "description": "When the priest casts a sanctuary spell, any opponent attempting to strike or otherwise directly attack the protected creature must roll a saving throw vs. spell. If the saving throw is successful, the opponent can attack normally and is unaffected by that casting of the spell. If the saving throw is failed, the opponent loses track of and totally ignores the warded creature for the duration of the spell. Those not attempting to attack the subject remain unaffected. Note that this spell does not prevent the operation of area attacks (fireball, ice storm, etc.). While protected by this spell, the subject cannot take direct offensive action without breaking the spell, but may use nonattack spells or otherwise act in any way that does not violate the prohibition against offensive action. This allows a warded priest to heal wounds, for example, or to bless, perform an augury, chant, cast a light in the area (but not upon an opponent), and so on.\nThe components of the spell include the priest's holy symbol and a small silver mirror.",
      "reversible": false,
      "source_document": "Player's Handbook",
      "source_page": 141,
      "confidence": 1.0,
      "needs_review": false
    }
  },
  {
    "input": "**Remove Fear**\n(Abjuration)\nReversible\nSphere: Charm\nRange: 10 yds. Components: V, S\nDuration: Special Casting Time: 1\nArea of Effect: 1 creature/4 levels Saving Throw: Special\n\nThe priest casting this spell instills courage in the spell recipient, raising the creature's saving throw rolls against magical fear attacks by +4 for one turn. If the recipient has recently (that day) failed a saving throw against such an attack, the spell immediately grants another saving throw, with a +4 bonus to the die roll. For every four levels of the caster, one creature can be affected by the spell (one creature at levels 1 through 4, two creatures at levels 5 through 8, etc.). \n The reverse of the spell, _cause fear_, causes one creature to flee in panic at maximum movement speed away from the caster for 1d4 rounds. A successful saving throw against the reversed effect negates it, and any Wisdom adjustment also applies. Of course, cause fear can be automatically countered by remove fear and vice versa. \n Neither spell has any effect on undead of any sort.",
    "output": {
      "name": "Remove Fear",
      "class_list": "Priest",
      "school": ["Abjuration"],
      "sphere": ["Charm"],
      "level": 1,
      "range": "10 yds.",
      "components": ["V", "S"],
      "duration": "Special",
      "casting_time": "1",
      "area_of_effect": "1 creature/4 levels",
      "saving_throw": "Special",
      "description": "The priest casting this spell instills courage in the spell recipient, raising the creature's saving throw rolls against magical fear attacks by +4 for one turn. If the recipient has recently (that day) failed a saving throw against such an attack, the spell immediately grants another saving throw, with a +4 bonus to the die roll. For every four levels of the caster, one creature can be affected by the spell (one creature at levels 1 through 4, two creatures at levels 5 through 8, etc.). \n The reverse of the spell, _cause fear_, causes one creature to flee in panic at maximum movement speed away from the caster for 1d4 rounds. A successful saving throw against the reversed effect negates it, and any Wisdom adjustment also applies. Of course, cause fear can be automatically countered by remove fear and vice versa. \n Neither spell has any effect on undead of any sort.",
      "reversible": true,
      "source_document": "Player's Handbook",
      "source_page": 155,
      "confidence": 1.0,
      "needs_review": false
    }
  }
]
```

Include examples that cover: (a) a reversible spell, (b) a spell with material components in the description, (c) a Priest spell with sphere and school, (d) a spell with "Special" in multiple fields, (e) a Wizard spell with multiple schools.

---

## 9. Error Handling

| Error | Handling |
|---|---|
| API key missing or invalid | Show a modal dialog prompting the user to open Settings. Block extraction until resolved. |
| Anthropic API rate limit (429) | Handled natively by Anthropic SDK `max_retries` limit. Only surface a fatal error with a "Retry" button if all automatic retries are exhausted. |
| Anthropic API error (5xx) | Log full response. **Stage 1 (per page):** skip that page’s boundary pass, emit `error` signal, continue to the next page. **Stage 2 (per spell):** skip only that spell after retries are exhausted — insert a placeholder `Spell` with `confidence=0.0`, `needs_review=True`, and `review_notes` citing the HTTP error; continue Stage 2 for remaining spells. |
| PDF is password-protected | Show dialog: "This PDF is encrypted. Please provide the password or remove protection." |
| Marker/Surya fails on a page | Fall back to `pytesseract`. Show "OCR Mode: Basic (CPU)" warning in UI and force `needs_review=True` for all spells on that page. |
| `LaxSpell` extraction fails after 3 Instructor retries (catastrophic — LLM returned unparseable output) | Log the raw response, create a placeholder spell with `confidence=0.0`, `needs_review=True`, `review_notes="Extraction failed: unparseable LLM response"`. Add to review queue. |
| `LaxSpell.to_spell()` strict validation fails (normal — partial or malformed fields) | Construct a best-effort `Spell` with parseable fields carried over, `confidence=0.0`, `needs_review=True`, and `review_notes` populated with Pydantic `ValidationError` messages (see §2.4). Route to review queue. |
| File not found or unreadable | Show `QMessageBox.critical` and abort import. |
| `session.json` unreadable/invalid | Rename to `session.json.bad.<UTC-timestamp>`, show one `QMessageBox.warning`, continue as no-session state. |
| PyInstaller frozen path issues with Tesseract | Auto-detect `sys.frozen` and set `pytesseract.tesseract_cmd = sys._MEIPASS + "/tesseract/tesseract.exe"`. Crucially, you must also set `os.environ["TESSDATA_PREFIX"] = sys._MEIPASS + "/tesseract/tessdata"` or the OCR process will crash on load. |

---

## 10. Build and Packaging

### PyInstaller specs (`build/spell_scribe_std.spec`, `build/spell_scribe_pro.spec`)

Key Standard-build options:
```python
a = Analysis(
    ['main.py'],
    datas=[
        ('resources/', 'resources/'),
        ('tesseract/', 'tesseract/'),
    ],
  hiddenimports=['pydantic', 'instructor'],
  excludes=['marker', 'torch', 'torchvision', 'transformers', 'accelerate'],
)
exe = EXE(a.pure, ..., name='SpellScribe', windowed=True, icon='resources/icon.ico')
```

The Pro spec keeps the Marker and PyTorch stack and omits the Standard-build `excludes` list.

### Build Flavors
The application is packaged in two "flavors" to manage binary size:
- **SpellScribe Standard**: (~150MB) Includes Tesseract CPU OCR.
- **SpellScribe Pro**: (3GB+) Includes `marker-pdf` with PyTorch and CUDA runtimes.

**Important packaging requirement for the Standard build:**
PyInstaller will naturally trace imports and bundle PyTorch into both builds if not strictly prevented. You MUST use a **lazy import** for `marker-pdf` (i.e. importing it only locally inside the extraction function guarded by a `try/except ImportError`). Furthermore, the `spell_scribe_std.spec` file must explicitly exclude the heavy deep-learning stack:
`excludes=['marker', 'torch', 'torchvision', 'transformers', 'accelerate']`

Build commands:
```bat
:: Standard Build
pyinstaller build/spell_scribe_std.spec --clean
:: Pro Build
pyinstaller build/spell_scribe_pro.spec --clean
```

### Inno Setup (`build/installer.iss`)

```ini
[Setup]
AppName=SpellScribe
AppVersion=1.0.0
DefaultDirName={autopf}\SpellScribe
OutputDir=dist
OutputBaseFilename=SpellScribe_Setup

[Files]
Source: "dist\SpellScribe\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{autoprograms}\SpellScribe"; Filename: "{app}\SpellScribe.exe"
```

---

## 11. Development Phases

Build and test in this order. Each phase is a standalone prompt to Claude.

### Phase 0 — Ingestion and Metadata
- **Document Identity Dialog**: New modal for **source document display name** and **PDF-to-Book page offset**. Persist the offset in `AppConfig.document_offsets` keyed by the **SHA-256 hash** of the source file (not by display name).
- `app/pipeline/detector.py` update to handle offset logic and **Force OCR** lookups (`force_ocr_by_sha256`).

### Phase 1 — Data model and pipeline skeleton
- `app/models.py` (Spell, LaxSpell, TextRegion, CoordinateAwareTextMap — full schema from §2)
- `app/session.py` (`SpellRecord`, `SessionState`, autosave/load helpers)
- `app/config.py` (AppConfig)
- `app/pipeline/ingestion.py` (route_document, PDF/DOCX branches)
- `app/pipeline/detector.py` (is_scanned_pdf)
- Unit tests for validators and ingestion routing using sample files

**Deliverable**: `python -m pytest tests/` passes with at least 10 tests.

### Phase 2 — Extraction pipeline
- `app/pipeline/extraction.py` (both LLM stages, Instructor integration)
- `resources/few_shot_examples.json` (at least 4 examples)
- CLI test harness: `python extract_cli.py --file sample.pdf` prints extracted spells as JSON to stdout

**Deliverable**: Given a single PDF page with 2–3 spells, the CLI outputs valid JSON matching the schema.

### Phase 3 — Export
- `app/pipeline/export.py` (to_json, to_markdown)
- `resources/templates/spell.md.j2` (Jinja2 template)
- Tests for both export formats

**Deliverable**: Given a `list[Spell]` plus export options (§6.0 / §6.1 / §6.2), produces **JSON `version` 1.1** (with provenance fields) and Markdown files that stay in sync with the same filters.

### Phase 4 — Main window shell and threading
- `app/ui/main_window.py` (toolbar, splitter, status bar)
- `app/ui/spell_list_panel.py` (QListWidget with three sections)
- `ExtractionWorker` QThread with discovery and extraction signals
- Connect worker signals to list panel

**Deliverable**: Window opens, "Open File" dialog works, progress bar animates during a mock extraction run.

### Phase 5 — Document panel
- `app/ui/document_panel.py` (PDF page rendering, DOCX text view)
- Bounding box highlight when a spell is selected

**Deliverable**: Loading a PDF renders page images; selecting a spell in the list highlights its region.

### Phase 6 — Review panel
- `app/ui/review_panel.py` (draft-backed form plus pending status view)
- Draft editing flow between `SpellRecord.draft_spell` and `SpellRecord.canonical_spell`
- Accept / Save Changes / Discard Draft / Delete / Re-extract buttons wired up

**Deliverable**: Selecting a pending record shows status details; selecting an extracted record populates the draft form; editing a field updates the draft only; Accept or Save Changes commits the canonical record.

### Phase 7 — Settings dialog, final wiring, and polish
- Settings dialog (§5.5)
- Export buttons wired to export functions
- Error handling for all cases in §9
- Status bar messages

**Deliverable**: Full end-to-end run: open a scanned PDF → extract → review one spell → export JSON. No unhandled exceptions.

### Phase 8 — Packaging
- `build/spell_scribe_std.spec`
- `build/spell_scribe_pro.spec`
- `build/installer.iss`
- README with setup instructions and Tesseract install note

**Deliverable**: `SpellScribe_Setup.exe` installs and runs on a clean Windows machine.

---

## 12. Out of Scope (do not implement unless asked)

- Cross-document spell library or database (session persistence exists solely for mid-session recovery — resuming "where you left off" if a session is interrupted, not for retaining spells across separate import runs)
- Cloud sync or user accounts
- Batch API support (Anthropic Batch)
- macOS or Linux builds
- Monster stat block extraction
- Any AD&D 1e, D&D 5e, or other system
- Auto-detection of the source book title from cover pages
