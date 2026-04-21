# The right stack for an AD&D 2e spell extractor

**Build it in Python with PySide6, use Claude Haiku 4.5 with vision (skip standalone OCR), wrap structured output with Instructor + Pydantic, and keep Marker/Surya as a local fallback.** This combination minimizes moving parts, leverages the only ecosystem (Python) where every required capability — PDF rendering, DOCX parsing, OCR, vision-LLM SDKs, schema validation — is mature, and produces a single PyInstaller-built `.exe` for Windows. For an AD&D 2e spellbook specifically, the work is also smaller than it looks: a partial dataset already exists, so you should bootstrap from `ChrisSSocha/dnd-2e-data` and `vodabois.fi/2eSpells` rather than OCR'ing every page from scratch.

The rest of this report justifies each piece of that recommendation, walks through the pipeline architecture, and flags the few real decision points that depend on your priorities (cost vs. offline operation, native look vs. development speed).

## Why Python beats Electron, Tauri, and .NET here

The deciding factor is that **every "hard" subsystem in your spec — PDF rendering, OCR, DOCX parsing, vision LLM calls, schema validation — has its strongest, best-documented implementation in Python**. Choosing JavaScript, Rust, or C# means either reimplementing those tools (weeks of work, worse accuracy) or shipping a Python sidecar inside Electron/Tauri — which gives you two package managers, two build pipelines, IPC overhead, and PyInstaller-bundled binaries to ship anyway. Every blog post advocating that pattern treats it as a reluctant workaround. **For a solo hobbyist on Windows-only, one language and one toolchain wins on velocity and reliability.**

The specific dismissals: Electron costs you ~150 MB baseline, ~250 MB RAM, plus a Python sidecar regardless. Tauri's tiny bundles are the opposite of what matters for a doc-processing app — you'll re-add a 50 MB Python runtime the moment you need OCR. .NET's `Windows.Media.Ocr` is decent for modern docs but weak on stylized fantasy fonts, iText's AGPL license is a distribution trap, and there's no first-party Anthropic SDK. Go + Wails has the same ecosystem problem as Rust with a smaller community.

## GUI: PySide6 first, NiceGUI as a faster alternative

**PySide6 (Qt 6 with LGPL licensing) is the right pick.** Spell blocks are a structured-record editor — exactly what `QAbstractTableModel` + `QStyledItemDelegate` were built for. Qt gives you a three-pane workflow (PDF viewer left, extracted block middle, JSON preview right), drag-to-reorder, syntax-highlighted Markdown via `QSyntaxHighlighter`, and the most mature PyInstaller hook of any Qt binding. Avoid PyQt6 — same code, but its GPL-or-commercial license is a footgun if you ever distribute the binary. Skip Tkinter (editable tables and rich text are painful), Streamlit (it reruns the whole script on every edit — wrong model for an editor), and Briefcase/Toga (still too immature for an app this complex).

**The runner-up worth considering is NiceGUI in native (pywebview) mode.** Same Python backend, Vue/Quasar UI with much less boilerplate than Qt's signals/slots — at the cost of ~2-second startup vs Qt's ~1 second and a slightly less native feel. Pick it if Qt's model/view classes annoy you; otherwise PySide6 is more capable for a multi-pane review UI.

## Document ingestion: a two-track pipeline

The cleanest architecture **routes by file type and PDF status**:

```
input.pdf  →  fitz.open  →  is_scanned()?
                                 │
                  ┌──────────────┴──────────────┐
              native                         scanned
                  │                              │
           pymupdf4llm                       Marker
           .to_markdown()                  (Surya OCR +
                  │                       layout model)
                  └──────────────┬──────────────┘
                                 ▼
                        Markdown with bold/italic
                                 │
input.docx → docx2python(html=True) → tagged paragraphs ──┘
                                 ▼
                  Style-aware normalizer
                  (dehyphenate, collapse columns,
                   tag FIELD_LABEL / SPELL_NAME / BODY)
                                 ▼
                Spell-block splitter (regex on names)
                                 ▼
              Per-block extraction (Claude vision + text)
                                 ▼
                Pydantic validation → confidence gate
                                 ▼
             {valid spells} → JSON / Markdown export
             {low-confidence} → review UI
```

**For PDFs**, use **PyMuPDF (`fitz`) + PyMuPDF4LLM** for digitally-born PDFs (fast, pure-CPU, ~0.1s/page, preserves headers and tables in Markdown), and **Marker** for scanned ones — Marker bundles Surya OCR with a layout model that solves 2-column reading order, exactly the failure mode of raw Tesseract on TSR books. Detection is reliable via PyMuPDF: treat as scanned if total `get_text()` length is under ~1% of file size, if any page has a near-full-page image, or if the font name `GlyphlessFont` appears.

**For DOCX**, use **`docx2python` v3 with `html=True`**. Its killer feature is run-level `<b>`/`<i>` HTML tags emitted alongside paragraph style names in one nested structure — you can detect `<b>Range:</b>` or italicized spell names with a single iteration. Reach for `python-docx` only when you need per-run font-attribute control. Skip mammoth (only useful if your sources have disciplined Word styles, which RPG documents rarely do) and docx2txt (loses all formatting cues).

## OCR: the 2026 answer is "let Claude see the page"

**The best OCR is no separate OCR step at all.** As of 2026, Claude 4.x's PDF/image endpoint already rasterizes each page and interleaves page images with extracted text in the prompt. Sending images directly is strictly a superset of "run Tesseract first" — it recovers ligature errors (`rn`→`m`), uses visual cues like bold and italic (which Tesseract loses), and handles the column layout that breaks classical OCR.

Keep one **local fallback** for offline use, low-confidence pages, or to avoid API cost on bulk runs: **Surya OCR via Marker** is the top open-source choice (local, layout-aware, Markdown output, Apache-licensed). **Mistral OCR 3** at ~$1 per 1,000 pages is the runner-up if a page defeats Surya — at hobby volumes it's effectively free. Plain Tesseract still works if you preprocess (deskew, binarize, PSM tuning), but with Surya available there's little reason to reach for it.

The one configuration change worth making: pass Tesseract output (or Surya output) **alongside** the page image to Claude as a `<page_text>` block. Anthropic's own PDF endpoint does this internally, and it's a cheap "belt and suspenders" against vision-only mistakes.

## LLM extraction: Instructor + Pydantic + Haiku 4.5, two-stage

**Use Instructor (`instructor.from_provider("anthropic/claude-haiku-4-5-latest", mode=Mode.TOOLS)`) with Pydantic models.** Claude has no constrained-decoding equivalent to OpenAI's `response_format: json_schema`, so the official Anthropic recommendation is **tool use with `tool_choice` forcing a specific tool** — exactly what Instructor wraps. You get auto-retries that feed Pydantic's `ValidationError` back into the chat, partial streaming, and identical syntax if you swap models. BAML is the only competitive alternative and is worth it only if you'll later expose the pipeline to TypeScript clients. Outlines doesn't work with hosted Claude. LangChain's structured output is heavyweight overkill.

**Run extraction in two stages.** Single-pass "find and extract every spell in this PDF" produces unbounded outputs that degrade Claude's tool-use reliability and let one bad block corrupt adjacent ones. Instead:

1. **Boundary detection**: send a whole page (image + OCR text) to Haiku 4.5 with a tiny schema returning `[{spell_name, page, bbox}]`. Vision handles this far better than text heuristics because OCR mangles italic field labels.
2. **Per-spell extraction**: for each detected block, send only that cropped region with the full schema and 2–4 few-shot examples of noisy-OCR-to-clean-JSON. Flat schema, small context, parallelizable, easy to retry.

For the prompt itself, follow Anthropic's own guidance: **XML tags to delimit instructions, schema, examples, and raw data**; cache the system prompt + schema + few-shot prefix (cuts cached-input tokens to ~10% of base rate); ask the model for **per-field confidence scores** so you can route low-confidence blocks to the human-review UI automatically.

**Model choice and cost (April 2026 pricing).** Use **Claude Haiku 4.5** ($1/$5 per million input/output tokens) as the default — quality on stat-block extraction is essentially indistinguishable from Sonnet for this rigid format. Fall back to **Claude Sonnet 4.6** ($3/$15) only when validation fails or confidence drops below ~0.85. A typical 100-page spell appendix (~400 spells) costs **~$1.10 with Haiku 4.5**, or roughly half that via the Batch API. Opus 4.7 is unnecessary here.

**Validation is layered**: Pydantic `Literal` enums for school (eight 2e schools), `conint(ge=1, le=9)` for level, `set[Literal["V","S","M"]]` for components, plus regex validators for the rigid AD&D 2e patterns (`Range` matches `Touch|0|\d+ yds(/level)?|Special`, `Casting Time` matches `\d+|\d+ rds?|\d+ turns?|Special`, `Saving Throw` is one of about a dozen exact strings). Anything that fails validation or has low per-field confidence routes to a Qt review form bound to the same Pydantic model — accept/edit/reject and persist corrections as new few-shot examples.

## What already exists for AD&D 2e

This is the most underappreciated finding: **you don't have to start from zero**.

- **`ChrisSSocha/dnd-2e-data`** (GitHub) — CSVs of priest + wizard spell *names + levels + sources* across PHB, Tome of Magic, Spells & Magic, Complete Wizard's Handbook, and the Faiths & Avatars line. Names and levels only, no descriptions, but it's a canonical enumeration that saves you the spell-discovery problem.
- **`vodabois.fi/2eSpells`** — A static HTML table with descriptions for ~60–70% of 2e spells. Single-table scrape, trivial to parse.
- **`decheine/complete-compendium`** — Thousands of AD&D 2e *monsters* already harvested from the lomion.de archive into JSON. If monsters are ever in scope, fork this rather than OCR'ing the Monstrous Compendium.
- **`ezdm` (ajventer)** — Python DM tool with bundled 2e JSON data files; useful for schema inspiration.
- **`iwd32900/textract-dnd-statblock`** — The closest working precedent for any TTRPG PDF→JSON pipeline. 5e-focused but its two-column detection and sequential-field regex approach port directly to 2e's rigid format.
- **Schema templates**: model your output on **Open5e v2** and **5etools** conventions (nested `{value, unit, type}` for range, typed components, source-document keys). Their schemas already handle the edge cases you'll hit.

There is **no complete machine-readable AD&D 2e spell dataset**, especially for the Wizard's Spell Compendium and Priest's Spell Compendium — that's the real gap your tool fills. The pragmatic plan is: download what exists, OCR + extract only the missing portion, and reformat everything into one schema.

## Recommended dependency pin

```
pip install pyside6 pymupdf pymupdf4llm marker-pdf docx2python python-docx \
            anthropic instructor pydantic pillow pytesseract jinja2
# optional cloud OCR fallback:
pip install mistralai
```

Bundle Tesseract 5.5 from UB-Mannheim's Windows installer **only as the offline fallback** (Marker provides Surya, which is better). Ship `tesseract.exe` plus `tessdata/eng.traineddata` (~15 MB) inside your PyInstaller bundle and detect the frozen path at startup; using `--windowed`, launch the subprocess with `creationflags=CREATE_NO_WINDOW` or it will fail silently (PyInstaller issue #5601). Package with **PyInstaller 6.x** in one-folder mode for development and one-file for release, then wrap in **Inno Setup** for a real installer. Expect ~150 MB installed with Tesseract bundled, ~80 MB without.

## Conclusion

The 2026 stack collapses what would have been a multi-component pipeline two years ago into something almost embarrassingly simple: **PySide6 frontend, PyMuPDF + Marker for ingestion, Claude Haiku 4.5 vision + Instructor for extraction, Pydantic for validation, PyInstaller + Inno Setup for shipping**. The reason this works is that vision-capable LLMs have absorbed both OCR and structured extraction into a single API call with per-field confidence — making the classical OCR → layout → regex pipeline largely obsolete except as a local fallback. Combined with the existing partial 2e datasets, the practical engineering problem is no longer "how do I extract spell blocks" but "how do I build a good review UI for the ~10–15% of blocks where the model isn't confident." That's a Qt application, not a machine-learning project — which is exactly the right framing for a single-developer hobby tool.