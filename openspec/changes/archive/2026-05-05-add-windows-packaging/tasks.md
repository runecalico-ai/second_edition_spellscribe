## Sequencing

- Implement last, after all runtime changes are in place.
- Freeze only after the shell, pipeline, settings, and export behavior are stable enough to package and smoke-test.

## 1. Resources and Assets

- [x] 1.1 Update `build/build_all.ps1` to automatically detect and report system Tesseract 5.5 binaries and `eng.traineddata` paths for later bundling steps
- [x] 1.2 Create or source application icons (`.ico`) and ensure they are discoverable by the build script
- [x] 1.3 Add `resources/license.txt` for the Inno Setup installer

## 2. Build specs

- [x] 2.1 Add `build/spell_scribe_std.spec` with Standard-build datas, hidden imports, and explicit excludes for `marker`, `torch`, etc.
- [x] 2.2 Add `build/spell_scribe_pro.spec` with the Pro-build dependency set and shared resources
- [x] 2.3 Add `build/build_all.ps1` PowerShell script to automate PyInstaller and ISCC (Inno Setup) calls

## 3. Frozen runtime behavior

- [x] 3.1 Refactor `app/paths.py` to handle centralized frozen-path resolution for Tesseract and tessdata
- [x] 3.2 Update `app/pipeline/ingestion.py` to use `app/paths.py` and implement automatic `TESSDATA_PREFIX` lookup
- [x] 3.3 Implement build-flavor constant injection in `app/build_config.py` (or similar) via PyInstaller `hook-app.py` or `.spec` logic
- [x] 3.4 Audit Marker import sites and convert them to guarded lazy imports where needed
- [x] 3.5 Update Settings UI to gate Pro-only features and display "Standard Edition" vs "Pro Edition" labels

## 4. Installer and docs

- [x] 4.1 Add `build/installer.iss` with preprocessor defines for Standard/Pro build parameterization
- [x] 4.2 Add README packaging and install notes for Standard and Pro builds

## 5. Verification

- [x] 5.1 Verify Standard build: Ensure no `torch` / `marker` stack under `dist/SpellScribe-Standard` (automated via `build/verify_packaging.ps1`; optional `-SmokeExe`; see README).
- [x] 5.2 Verify Pro build: Ensure Pro onedir contains Marker/Torch artifacts (`build/verify_packaging.ps1`); CUDA/Marker functional OCR + `ocr_backend` in `route_document` remain manual until wired (README).
- [x] 5.3 Verify Installer: Ensure `dist/installer` has flavor setup programs (`build/verify_packaging.ps1`); shortcuts/ARP/registry checks stay manual per release (README).


