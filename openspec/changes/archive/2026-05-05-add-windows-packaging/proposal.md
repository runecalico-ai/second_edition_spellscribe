## Why

Windows packaging is valuable, but it is not a good reason to block the rest of the application work. Splitting packaging into its own change keeps runtime behavior separate from distribution concerns and makes the Standard-versus-Pro build rules explicit.

## What Changes

- Add Standard and Pro PyInstaller spec files.
- Enforce lazy Marker imports and Standard-build excludes for the heavy ML stack.
- Add frozen-path initialization rules for bundled Tesseract and tessdata.
- Add the Inno Setup installer script.
- Add README packaging and install notes for Windows.

## Capabilities

### New Capabilities
- `windows-packaging`: Windows build, installer, and frozen-runtime behavior for SpellScribe distribution.

### Modified Capabilities
- None.

## Impact

- Affected code: `build/spell_scribe_std.spec`, `build/spell_scribe_pro.spec`, `build/installer.iss`, runtime startup code, `README*`
- Affected behavior: Windows builds, bundled resources, Tesseract startup, and installer output
- Dependencies: `PyInstaller`, `Inno Setup`, bundled Tesseract assets
