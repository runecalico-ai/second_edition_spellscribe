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
| Templating (Markdown export) | `jinja2` | latest |
| Packaging | `PyInstaller 6.x` + Inno Setup | latest |

**Dependencies Note**: The application includes a fallback mode for systems without NVIDIA GPUs. `marker-pdf` (Surya) is used when CUDA is available; otherwise, the app defaults to `pytesseract` for OCR.

**Python version**: 3.11 (required by marker-pdf).

Install command:
```
pip install pyside6 pymupdf pymupdf4llm marker-pdf docx2python \
            anthropic instructor pydantic pillow pytesseract jinja2
```

Tesseract binary ships **separately** inside the PyInstaller bundle at `./tesseract/tesseract.exe`. At runtime, detect the frozen path and set `pytesseract.pytesseract.tesseract_cmd` accordingly.

---

## 2. Data Model

All spell data is represented by the following Pydantic v2 model. This is the canonical schema for the entire application — ingestion, storage, validation, export, and the review UI all derive from it.

### 2.1 Design rules (match the main application's spell schema)

| Rule | Detail |
|---|---|
| **School vs Sphere** | Wizard spells populate `school`; Priest spells populate `sphere`. The other field is `None`. A `model_validator` enforces this. |
| **Wizard level** | Integer `0`–`9`. Cantrips are stored as `0`. If the source text says `"Cantrip"`, normalise to `0` during extraction. |
| **Priest level** | Integer `1`–`7`. Quest spells are stored as `8`. If the source text says `"Quest"`, normalise to `8` during extraction. |
| **Combined schools** | Slash-separated schools such as `"Invocation/Evocation"` are valid single `WizardSchool` values — do not split them. |

### 2.2 Enumerations

```python
from pydantic import BaseModel, field_validator, model_validator
from typing import Literal, Optional, Union
from enum import Enum


class WizardSchool(str, Enum):
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


# Note: The UI treats these Enums as "Suggested" values.
# The AppConfig stores a `custom_schools` and `custom_spheres` list to extend these.


class SpellCasterType(str, Enum):
    WIZARD  = "Wizard"
    PRIEST  = "Priest"


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
    caster_type: SpellCasterType
    level: SpellLevel

    # Exactly one of these is populated; the other is None (enforced by model_validator)
    school: Optional[WizardSchool] = None   # Wizard spells only
    sphere: Optional[PriestSphere] = None   # Priest spells only

    # ── Stat block fields ─────────────────────────────────────────────────
    range: str                       # e.g. "0", "Touch", "30 yds", "10 yds/level", "Special"
    components: list[Component]
    material_component: Optional[str] = None   # described if M is present
    duration: str                    # e.g. "1 rd/level", "Permanent", "Special"
    casting_time: str                # e.g. "1", "3", "1 rd", "1 turn", "Special"
    area_of_effect: str              # e.g. "One creature", "30-ft. radius", "Special"
    saving_throw: str                # e.g. "None", "Neg.", "½", "Special"

    # ── Description ───────────────────────────────────────────────────────
    description: str                 # full spell description, plain text
    reversible: bool = False         # True if spell has a reversed form
    reversed_name: Optional[str] = None

    # ── Source tracking ───────────────────────────────────────────────────
    source_document: str             # e.g. "Player's Handbook", "Tome of Magic"
    source_page: Optional[int] = None  # **book** page number (not raw PDF page); offset applied during extraction

    # ── Quality metadata (not exported) ───────────────────────────────────
    confidence: float = 1.0          # 0.0–1.0; populated by extraction pipeline
    needs_review: bool = False
    review_notes: Optional[str] = None

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
    def validate_school_sphere_exclusivity(self) -> "Spell":
        """Enforce that wizard spells have school and priest spells have sphere."""
        if self.caster_type == SpellCasterType.WIZARD:
            if self.school is None:
                raise ValueError("Wizard spells must have a school.")
            if self.sphere is not None:
                raise ValueError("Wizard spells must not have a sphere.")
        elif self.caster_type == SpellCasterType.PRIEST:
            if self.sphere is None:
                raise ValueError("Priest spells must have a sphere.")
            if self.school is not None:
                raise ValueError("Priest spells must not have a school.")
        return self

    @model_validator(mode="after")
    def validate_level_range_by_type(self) -> "Spell":
        """Enforce per-caster level ranges: Wizard 0–9, Priest 1–8."""
        if self.caster_type == SpellCasterType.WIZARD and not (0 <= self.level <= 9):
            raise ValueError(f"Wizard spell level must be 0–9, got {self.level}")
        if self.caster_type == SpellCasterType.PRIEST and not (1 <= self.level <= 8):
            raise ValueError(f"Priest spell level must be 1–8 (8 = Quest), got {self.level}")
        return self

    @model_validator(mode="after")
    def flag_missing_reversed_name(self) -> "Spell":
        """If reversible but no reversed name, flag for review."""
        if self.reversible and not self.reversed_name:
            self.needs_review = True
            self.review_notes = (self.review_notes or "") + "Reversible spell but no reversed name found. "
        return self
```

### 2.4 Lax extraction model

Instructor targets a `LaxSpell` model during Stage 2 extraction. Every field is `Optional[str]` so the LLM can return partial or malformed data without crashing the call.

```python
class LaxSpell(BaseModel):
    """All-optional mirror of Spell used as the Instructor extraction target.
    Ensures partial LLM output is always captured for human review."""

    name: Optional[str] = None
    caster_type: Optional[str] = None
    level: Optional[str] = None
    school: Optional[str] = None
    sphere: Optional[str] = None
    range: Optional[str] = None
    components: Optional[list[str]] = None
    material_component: Optional[str] = None
    duration: Optional[str] = None
    casting_time: Optional[str] = None
    area_of_effect: Optional[str] = None
    saving_throw: Optional[str] = None
    description: Optional[str] = None
    reversible: Optional[bool] = None
    reversed_name: Optional[str] = None
    source_document: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    needs_review: Optional[bool] = None
    review_notes: Optional[str] = None
```

**Conversion flow** (`LaxSpell → Spell`):

1. Instructor extracts into `LaxSpell` (retries up to 3 times on schema errors).
2. `LaxSpell.to_spell()` attempts `Spell.model_validate(self.model_dump(exclude_none=True))`.
3. **Validation succeeds** → returns a strict `Spell` object, routed to §4.4 post-extraction logic.
4. **Validation fails** → constructs a best-effort `Spell` with:
   - `confidence = 0.0`
   - `needs_review = True`
   - `review_notes` populated with the Pydantic `ValidationError` messages
   - All parseable fields carried over; unparseable fields filled with sensible defaults (empty string, `False`, etc.)
   - Routed directly to the review queue so the user can fix fields in the Review Panel.

This ensures that even after 3 failed Instructor retries, the user always gets **something** to work with rather than a silent data loss.

### 2.5 Extraction output hint for the LLM

Include this in the Stage 2 extraction system prompt so Claude knows how to handle these rules:

```
Level normalisation:
- If the source text shows "Cantrip" for a Wizard spell, output level: 0
- If the source text shows "Quest" for a Priest spell, output level: 8
- Otherwise output level as an integer

School vs Sphere:
- Populate "school" for Wizard spells; leave "sphere" null
- Populate "sphere" for Priest spells; leave "school" null
- Combined schools (e.g. "Invocation/Evocation") are a single valid school value — do not split

Valid wizard schools: Abjuration, Alteration, Calling, Charm, Conjuration,
  Conjuration/Summoning, Creation, Dimension, Divination, Enchantment,
  Enchantment/Charm, Evocation, Illusion, Illusion/Phantasm, Invocation,
  Invocation/Evocation, Necromancy, Phantasm, Shadow, Summoning, Teleportation, Temporal

Valid priest spheres: All, Animal, Astral, Chaos, Charm, Combat, Creation, Desert,
  Destiny, Divination, Drow, Elemental Air, Elemental Earth, Elemental Fire,
  Elemental Water, Elemental Rain, Elemental Sun, Evil, Fate, Good, Guardian,
  Healing, Law, Magma, Necromantic, Numbers, Plant, Protection, Silt, Summoning,
  Sun, Thought, Time, Travelers, War, Weather
```

**Serialization rules**:
- JSON export omits `confidence`, `needs_review`, `review_notes`.
- Markdown export renders each spell as a structured block (see §7).
- The `school` key is omitted from Priest spell JSON; the `sphere` key is omitted from Wizard spell JSON.
- Internal storage uses a **Session Persistence** model keyed by the **SHA-256 hash** of the source file. Progress is auto-saved to `~/.spellscribe/session.json`. The session stores extracted `Spell` objects and the intermediate **Markdown** text (to avoid re-running OCR) but regenerates physical coordinates on load.
- **Single session at a time**: Only one document's extraction state is active. Opening a new file while a session exists prompts: *"You have unsaved work on [filename]. Export first, discard, or cancel?"* The session is cleared only when the user explicitly discards it or opens a new file and confirms. Export does **not** auto-clear the session (the user may want to re-export or continue reviewing).

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

**Session persistence note**: `CoordinateAwareTextMap` is **not** serialized to `session.json`. The intermediate Markdown text is stored, and coordinates are regenerated on session load by re-running the lightweight coordinate-extraction pass (no OCR or LLM calls needed).

---

## 3. Application Architecture

```
SpellScribe/
├── main.py                  # Entry point; launches QApplication
├── app/
│   ├── __init__.py
│   ├── config.py            # AppConfig dataclass (API key, confidence threshold, paths)
│   ├── models.py            # Spell, LaxSpell, TextRegion, CoordinateAwareTextMap (§2)
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
│       ├── spell_list_panel.py # Centre: QListWidget of extracted spells
│       └── review_panel.py  # Right: editable form for a single spell
├── resources/
│   ├── few_shot_examples.json   # 4–6 ground-truth spell extraction examples
│   └── templates/
│       └── spell.md.j2          # Jinja2 template for Markdown export
├── tesseract/               # Bundled Tesseract binary (Windows)
│   ├── tesseract.exe
│   └── tessdata/eng.traineddata
├── requirements.txt
└── build/
    ├── spell_scribe.spec    # PyInstaller spec
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
- If `.pdf`:
  - Open with `fitz.open(path)`.
  - For each page, compute `text_ratio = len(page.get_text()) / page.rect.area`.
  - If `text_ratio < 0.001` OR any embedded image covers >50% of the page area → mark as **scanned**.
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
Your task is to identify where each spell begins on a page.
Return ONLY a JSON array. No prose, no markdown fences.
```

**User message**:
```xml
<page_number>{n}</page_number>
<page_text>
{markdown_text}
</page_text>

Return a JSON array of objects: [{"spell_name": "...", "start_line": N}]
If no spells are found on this page, return [].
```

Parse the response with `json.loads`. If it fails, skip this page and log a warning.

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
- Level line: "Level: 3" or "Wizard 3" or "Priest 2"
- Range, Components, Duration, Casting Time, Area of Effect, Saving Throw
  (each on its own line, label in bold or followed by a colon)
- A blank line, then the full description paragraph(s)

Rules:
- A "Sphere:" label in the source text indicates a Priest spell — populate the `sphere` field (not `school`).
- If the spell is reversible, set reversible=true and capture the reversed form name.
- Material component text appears in the description after the "M" component is listed.
- Set confidence to a float between 0.0 and 1.0 reflecting your certainty.
  Set needs_review=true if confidence < 0.85 or any field is ambiguous.
- source_document and source_page are provided to you; copy them verbatim.

<few_shot_examples>
{few_shot_json}
</few_shot_examples>
```

**User message**:
```xml
<source_document>{doc_name}</source_document>
<source_page>{page_num}</source_page>          <!-- book page = pdf_page + offset -->
<spell_text>
{cropped_markdown}
</spell_text>
```

- **Sequential Discovery, Parallel Extraction**:
  - **Stage 1 (Discovery)**: A worker processes pages sequentially to build a manifest of spell boundaries. It only considers a spell "Ready for Stage 2" once the *next* spell's start point is found (ensuring page-spanning descriptions are captured) or the file ends.
  - **Stage 2 (Extraction)**: "Ready" spells are pushed to a parallel queue (capped at `AppConfig.max_concurrent_extractions`). Use exponential backoff for rate limits.
- **Lax Model**: Extraction first uses a `LaxSpell` model where all fields are optional strings. This ensures Claude can return "broken" or partially parsed data for manual review rather than failing the entire call on a minor schema violation.
- **Reversible Cloning**: If "Explode Reversible" is enabled, the application logic (not the LLM) creates a clone of the `Spell` object, using the `reversed_name` as the primary key for the second entry. If `reversed_name` is `None`, the spell is **not** cloned and is routed to the review queue instead (the `flag_missing_reversed_name` validator in §2.3 ensures `needs_review` is already set).
- On `ValidationError`, Instructor will automatically retry up to 3 times feeding the error back into the conversation.

### 4.4 Post-extraction routing

```python
CONFIDENCE_THRESHOLD = 0.85   # configurable in AppConfig

for spell in extracted_spells:
    if spell.confidence < CONFIDENCE_THRESHOLD or spell.needs_review:
        send_to_review_queue(spell)
    else:
        add_to_confirmed_list(spell)
```

---

## 5. User Interface

### 5.1 Main window layout

Three-panel layout using `QSplitter`:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Toolbar: [Open File] [Detect Spells] [Extract Selected] [Export]   │
│           [Settings]                              [Progress bar]    │
├──────────────────┬───────────────────┬────────────────────────────┤
│  Document Panel  │  Spell List Panel │  Review / Edit Panel       │
│  (left, 30%)     │  (centre, 25%)    │  (right, 45%)              │
│                  │                   │                            │
│  PDF page image  │  Extracted ✓      │  Editable form             │
│  or DOCX text    │  ────────────     │  for selected spell        │
│  rendered with   │  > Magic Missile  │                            │
│  highlighted     │  > Fireball       │                            │
│  bounding box    │  > Sleep          │                            │
│  for selected    │                   │                            │
│  spell           │  Found (Pending)  │                            │
│                  │  ────────────     │                            │
│                  │  > Bigby's Hand   │                            │
│                  │  > Wraithform     │                            │
└──────────────────┴───────────────────┴────────────────────────────┘
│  Status bar: "OCR Mode: Standard (CPU) | Found 47 spells | Page 12/34" │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Document Panel (`document_panel.py`)

- For PDFs: render current page as a `QPixmap` using PyMuPDF's `page.get_pixmap()`. Display in a `QLabel` inside a `QScrollArea`. Highlight the bounding box of the currently-selected spell with a semi-transparent yellow `QPainter` overlay.
- For DOCX: render the raw Markdown text in a `QPlainTextEdit` (read-only) with syntax highlighting for field labels (bold patterns → green, spell names → blue).
- Navigation arrows to page forward/back.

### 5.3 Spell List Panel (`spell_list_panel.py`)

- `QListWidget` with two sections separated by a visual divider: **Confirmed** (green checkmark icon) and **Needs Review** (amber warning icon).
- **Multi-Selection**: Supports SHIFT/CTRL selection for bulk right-click actions (Move to Confirmed, Delete).
- **Audit Sorting**: Users can sort the Confirmed list by confidence (ascending) to audit "Weak Greens."
- **Spanning Indicator**: Spells covering >1 page show a "two-page" icon.
- **Duplicate Indicator**: Spells with a naming conflict in the Confirmed list show a red overlap icon.
- Single-click selects a spell and updates the Review Panel and Document Panel highlight.
- Right-click context menu: **Move to Confirmed**, **Delete**, **Re-extract** (re-runs Stage 2 for this spell's page region).
- Shows spell name + level label + school/sphere as a two-line list item. Level label reads "Cantrip" when level = 0 (Wizard) or "Quest" when level = 8 (Priest); otherwise shows the integer.

### 5.4 Review / Edit Panel (`review_panel.py`)

Displays a form bound to the currently selected `Spell` object. All fields are editable. Layout:

```
Spell Name:     [_______________________________]
Caster Type:    ( Wizard )  ( Priest )
School:         [dropdown — WizardSchool values]   ← visible only when Wizard
Sphere:         [dropdown — PriestSphere values]   ← visible only when Priest
Level:          [spinbox 0–9]  [label: "Cantrip" if 0+Wizard | "Quest" if 8+Priest]
Range:          [________________________]
Components:     [x] V  [x] S  [ ] M
  Material:     [________________________]   (shown only if M checked)
Duration:       [________________________]
Casting Time:   [________________________]
Area of Effect: [________________________]
Saving Throw:   [________________________]
Reversible:     [ ] Yes   Reversed name: [________________]
Source Doc:     [________________________]
Source Page:    [spinbox] (Book p.131) | [label: PDF p.140]   ← book page is editable; PDF page derived from offset
                [Go to Start] [Go to End]   ← Only for page-spanning spells

Description:
[_____________________________________________]
[_____________________________________________]   (QPlainTextEdit, 8 rows)

Review Notes:   [________________________]
Confidence:     0.73  ⚠ Needs review

[ Accept & Move to Confirmed ]   [ Delete ]   [ Re-extract ]
```

- When **Caster Type** is toggled, the School/Sphere row swaps the visible dropdown and clears the hidden field on the model.
- The level spinbox range adjusts: Wizard allows 0–9; Priest allows 1–8.
- **Real-time Validation**: On every edit, the form runs `Spell.model_validate()` in its strict mode.
- **Guided UI**: Fields with validation errors are highlighted with **red borders** and a descriptive tooltip (from Pydantic's `loc` and `msg`).
- **Conflict Management**: Clicking **Accept** checks for existing `name` + `caster_type` duplicates in the Confirmed list. If found, a dialog offers **Over-write**, **Keep Both**, or **Skip**.
- **Guided Re-extract**: Clicking **Re-extract** prompts for a "Focus area" string (e.g. "Duration is wrong") which is injected into the Stage 2 prompt as `<user_correction>`.
- The **Accept** button is disabled until all strict validation errors are resolved.

### 5.5 Settings Dialog

Accessible from toolbar. Stores values in `AppConfig` which persists to `~/.spellscribe/config.json`.

```
Anthropic API Key:       [_____________________________]  [Test]
Stage 1 Model:           [dropdown: claude-haiku-4-5-latest ▾]  (boundary detection)
Stage 2 Model:           [dropdown: claude-sonnet-4-latest ▾]   (spell extraction)
Max Parallel Extractions:[spinbox 1–20, default 5]               (concurrent Stage 2 calls)
OCR Engine:              (Auto-detect) (Marker/GPU) (Tesseract/CPU)
Explode Reversible:      [x] Create separate entries for reversed spells
Confidence Threshold:    [slider 0.5–1.0, default 0.85]
Default Export Directory:[_____________________________]  [Browse]
Tesseract Path:          [_____________________________]  (auto-detected)
Source Document Name:    [_____________________________]  (pre-filled for next import)
```

Model dropdowns offer `claude-haiku-4-5-latest`, `claude-sonnet-4-latest`, and `claude-opus-4-latest`. The user can trade cost for accuracy (Haiku ~$0.25/M tokens, Sonnet ~$3/M, Opus ~$15/M).

### 5.6 Progress and threading

- All extraction runs on a `QThread` subclass (`ExtractionWorker`).
- Worker emits: `spell_extracted(Spell)`, `page_completed(int, int)`, `error(str)`, `finished()`.
- Main thread connects these signals to update the UI live as spells come in.
- A `QProgressBar` in the toolbar shows page progress.
- A **Cancel** button appears while extraction is running and calls `worker.requestInterruption()`.

---

## 6. Export

### 6.1 JSON export

```python
ALWAYS_EXCLUDE = {"confidence", "needs_review", "review_notes"}

def to_json(spells: list[Spell], path: str) -> None:
    """
    Export confirmed spells only (needs_review=False).
    Omit: confidence, needs_review, review_notes.
    Omit: school for Priest spells, sphere for Wizard spells.
    """
    data = []
    for s in spells:
        if s.needs_review:
            continue
        exclude = ALWAYS_EXCLUDE | (
            {"sphere"} if s.caster_type == SpellCasterType.WIZARD else {"school"}
        )
        data.append(s.model_dump(exclude=exclude))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "spells": data}, f, indent=2, ensure_ascii=False)
```

Output structure (Wizard spell example):
```json
{
  "version": "1.0",
  "spells": [
    {
      "name": "Magic Missile",
      "caster_type": "Wizard",
      "school": "Invocation/Evocation",
      "level": 1,
      "range": "60 yds + 10 yds/level",
      "components": ["V", "S"],
      "material_component": null,
      "duration": "Instantaneous",
      "casting_time": "1",
      "area_of_effect": "1–5 targets",
      "saving_throw": "None",
      "description": "Use of the magic missile spell ...",
      "reversible": false,
      "reversed_name": null,
      "source_document": "Player's Handbook",
      "source_page": 140
    },
    {
      "name": "Cure Light Wounds",
      "caster_type": "Priest",
      "sphere": "Healing",
      "level": 1,
      "range": "Touch",
      "components": ["V", "S"],
      "material_component": null,
      "duration": "Permanent",
      "casting_time": "5",
      "area_of_effect": "Creature touched",
      "saving_throw": "None",
      "description": "When casting this spell ...",
      "reversible": true,
      "reversed_name": "Cause Light Wounds",
      "source_document": "Player's Handbook",
      "source_page": 257
    }
  ]
}
```

### 6.2 Markdown export

Use **Jinja2** with the template at `resources/templates/spell.md.j2`:

```jinja2
## {{ spell.name }}{% if spell.reversible %} *(Reversible)*{% endif %}

{% if spell.school %}**School:** {{ spell.school }}{% else %}**Sphere:** {{ spell.sphere }}{% endif %} | **Level:** {{ spell.caster_type }} {{ spell.level }}

| Field | Value |
|---|---|
| Range | {{ spell.range }} |
| Components | {{ spell.components | join(", ") }}{% if "M" in spell.components %} *({{ spell.material_component }})*{% endif %} |
| Duration | {{ spell.duration }} |
| Casting Time | {{ spell.casting_time }} |
| Area of Effect | {{ spell.area_of_effect }} |
| Saving Throw | {{ spell.saving_throw }} |

{{ spell.description }}

{% if spell.reversible %}
**Reversed form:** {{ spell.reversed_name }}
{% endif %}

*Source: {{ spell.source_document }}{% if spell.source_page %}, p. {{ spell.source_page }}{% endif %}*

---
```

Export function concatenates all confirmed spells through this template and writes to a single `.md` file.

---

## 7. Configuration (`config.py`)

```python
from dataclasses import dataclass, field, fields
from pathlib import Path
import json, os

CONFIG_PATH = Path.home() / ".spellscribe" / "config.json"

@dataclass
class AppConfig:
    api_key: str = ""
    stage1_model: str = "claude-haiku-4-5-latest"    # boundary detection (cheap, fast)
    stage2_model: str = "claude-sonnet-4-latest"     # spell extraction (quality/cost balance)
    max_concurrent_extractions: int = 5              # parallel Stage 2 calls (1–20)
    confidence_threshold: float = 0.85
    export_directory: str = str(Path.home() / "Documents")
    tesseract_path: str = ""          # auto-detected if blank
    default_source_document: str = "Player's Handbook"
    last_import_directory: str = ""
    # "Learning" schema extensions
    custom_schools: list[str] = field(default_factory=list)
    custom_spheres: list[str] = field(default_factory=list)
    document_offsets: dict[str, int] = field(default_factory=dict)  # source_document → offset; book_page = pdf_page + offset

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

The API key is stored in plaintext in the user's home directory. For a hobby tool this is acceptable; note it in the README.

---

## 8. Few-Shot Examples File

`resources/few_shot_examples.json` must contain at least **4 examples** in the following format, drawn from real AD&D 2e spell blocks (use the PHB or Tome of Magic as sources):

```json
[
  {
    "input": "**Wish** (Conjuration/Summoning)\nLevel: 9\nRange: Unlimited\nComponents: V\nDuration: Special\nCasting Time: Special\nArea of Effect: Special\nSaving Throw: Special\n\nThe wish spell is a more potent version of a limited wish. If it is used to alter reality...",
    "output": {
      "name": "Wish",
      "Spell_list": "Wizard",
      "tradition": "ARCANE",
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
      "tradition": "ARCANE",
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
      "tradition": "ARCANE",
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
      "tradition": "DIVINE",
      "school": ["Abjuration"],
      "sphere":"Protection",
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
      "tradition": "DIVINE",
      "school": ["Abjuration"],
      "sphere": "Charm",
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

Include examples that cover: (a) a reversible spell, (b) a spell with a material component, (c) a Priest spell with a sphere, (d) a spell with "Special" in multiple fields.

---

## 9. Error Handling

| Error | Handling |
|---|---|
| API key missing or invalid | Show a modal dialog prompting the user to open Settings. Block extraction until resolved. |
| Anthropic API rate limit (429) | Exponential backoff: wait 2, 4, 8 seconds, then surface error with "Retry" button. |
| Anthropic API error (5xx) | Log full response, surface error message, skip page, continue. |
| PDF is password-protected | Show dialog: "This PDF is encrypted. Please provide the password or remove protection." |
| Marker/Surya fails on a page | Fall back to `pytesseract`. Show "OCR Mode: Basic (CPU)" warning in UI and force `needs_review=True` for all spells on that page. |
| `LaxSpell` extraction fails after 3 Instructor retries (catastrophic — LLM returned unparseable output) | Log the raw response, create a placeholder spell with `confidence=0.0`, `needs_review=True`, `review_notes="Extraction failed: unparseable LLM response"`. Add to review queue. |
| `LaxSpell.to_spell()` strict validation fails (normal — partial or malformed fields) | Construct a best-effort `Spell` with parseable fields carried over, `confidence=0.0`, `needs_review=True`, and `review_notes` populated with Pydantic `ValidationError` messages (see §2.4). Route to review queue. |
| File not found or unreadable | Show `QMessageBox.critical` and abort import. |
| PyInstaller frozen path issues with Tesseract | Auto-detect `sys.frozen` and set `tesseract_cmd` to `sys._MEIPASS + "/tesseract/tesseract.exe"`. |

---

## 10. Build and Packaging

### PyInstaller spec (`build/spell_scribe.spec`)

Key options:
```python
a = Analysis(
    ['main.py'],
    datas=[
        ('resources/', 'resources/'),
        ('tesseract/', 'tesseract/'),
    ],
    hiddenimports=['pydantic', 'instructor', 'marker'],
)
exe = EXE(a.pure, ..., name='SpellScribe', windowed=True, icon='resources/icon.ico')
```

### Build Flavors
The application is packaged in two "flavors" to manage binary size:
- **SpellScribe Standard**: (~150MB) Includes Tesseract CPU OCR.
- **SpellScribe Pro**: (3GB+) Includes `marker-pdf` with PyTorch and CUDA runtimes.

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
- **Document Identity Dialog**: New modal for Book Name and PDF-to-Book page offset.
- `app/pipeline/detector.py` update to handle offset logic.

### Phase 1 — Data model and pipeline skeleton
- `app/models.py` (Spell, LaxSpell, TextRegion, CoordinateAwareTextMap — full schema from §2)
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

**Deliverable**: Given a `list[Spell]`, produces correct JSON and Markdown files.

### Phase 4 — Main window shell and threading
- `app/ui/main_window.py` (toolbar, splitter, status bar)
- `app/ui/spell_list_panel.py` (QListWidget with two sections)
- `ExtractionWorker` QThread with signals
- Connect worker signals to list panel

**Deliverable**: Window opens, "Open File" dialog works, progress bar animates during a mock extraction run.

### Phase 5 — Document panel
- `app/ui/document_panel.py` (PDF page rendering, DOCX text view)
- Bounding box highlight when a spell is selected

**Deliverable**: Loading a PDF renders page images; selecting a spell in the list highlights its region.

### Phase 6 — Review panel
- `app/ui/review_panel.py` (full editable form)
- Two-way binding between form fields and `Spell` objects
- Accept / Delete / Re-extract buttons wired up

**Deliverable**: Selecting a spell from the list populates the form; editing a field updates the in-memory object; Accept moves it to Confirmed.

### Phase 7 — Settings dialog, final wiring, and polish
- Settings dialog (§5.5)
- Export buttons wired to export functions
- Error handling for all cases in §9
- Status bar messages

**Deliverable**: Full end-to-end run: open a scanned PDF → extract → review one spell → export JSON. No unhandled exceptions.

### Phase 8 — Packaging
- `build/spell_scribe.spec`
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