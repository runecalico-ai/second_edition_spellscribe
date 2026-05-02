## Context

The revised spec requires two Windows packaging flavors: a Standard build that stays small and CPU-only, and a Pro build that includes Marker and the GPU stack. Packaging also needs frozen-runtime setup for the bundled Tesseract binary and an installer for Windows users.

This change depends on the runtime code being import-safe for PyInstaller. It does not change the user-facing extraction or review behavior.

## Goals / Non-Goals

**Goals:**
- Add Standard and Pro PyInstaller spec files.
- Keep the Standard build free of Marker and PyTorch through lazy imports and explicit excludes.
- Add frozen-runtime setup for Tesseract executable and tessdata.
- Add the Windows installer script and README notes.

**Non-Goals:**
- Implement extraction logic itself.
- Implement settings or export.
- Support macOS or Linux packaging.

## Decisions

### Maintain separate Standard and Pro spec files
- The Standard and Pro builds have different dependency footprints and size targets.
- Separate spec files make those constraints explicit.

Alternative considered:
- Use one spec file with runtime flags.
- Rejected because the heavy ML stack must be excluded at build time for the Standard build.

### Keep Marker imports lazy in runtime code
- PyInstaller can trace heavy dependencies even when they are optional.
- Local guarded imports are the safest way to keep the Standard build small.

Alternative considered:
- Rely on spec-file excludes only.
- Rejected because runtime imports can still pull in the heavy stack in less obvious ways.

### Set both `tesseract_cmd` and `TESSDATA_PREFIX` in frozen mode
- The app should not depend on system-installed Tesseract when running from the packaged bundle.
- Path resolution logic for Tesseract and tessdata is centralized in `app/paths.py`.

### Use explicit build-flavor constants
- A `BUILD_FLAVOR` constant (Standard vs Pro) is injected at build time.
- This drives UI labels and feature availability (e.g., "Standard Edition").

### Implement UI-level gating for Pro features
- The Standard build hides or disables Marker/GPU options in Settings.
- This prevents "broken" states where a user selects a feature missing from their build.

### Use --onedir PyInstaller format
- Avoids the slow startup of `--onefile` decompression, especially for the heavy Pro build.
- The Inno Setup installer provides the single-file setup experience for the user.

## Risks / Trade-offs

- Build specs can drift from runtime imports → Keep lazy-import rules documented and testable.
- Standard and Pro artifacts can diverge in resource layout → Keep shared datas consistent across spec files.
- Installer scripts can break after build-output changes → Keep output paths explicit and document them in the README.

## Migration Plan

- No migration is required.

## Open Questions

- None for this change.
