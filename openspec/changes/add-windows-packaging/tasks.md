## Sequencing

- Implement last, after all runtime changes are in place.
- Freeze only after the shell, pipeline, settings, and export behavior are stable enough to package and smoke-test.

## 1. Resources and Assets

- [ ] 1.1 Source Tesseract 5.5 binaries and `eng.traineddata` and place in `tesseract/` project directory
- [ ] 1.2 Create or source application icons (`.ico`) for Standard and Pro builds
- [ ] 1.3 Add `resources/license.txt` for the Inno Setup installer

## 2. Build specs

- [ ] 2.1 Add `build/spell_scribe_std.spec` with Standard-build datas, hidden imports, and explicit excludes for `marker`, `torch`, etc.
- [ ] 2.2 Add `build/spell_scribe_pro.spec` with the Pro-build dependency set and shared resources
- [ ] 2.3 Add `build/build_all.ps1` PowerShell script to automate PyInstaller and ISCC (Inno Setup) calls

## 3. Frozen runtime behavior

- [ ] 3.1 Refactor `app/paths.py` to handle centralized frozen-path resolution for Tesseract and tessdata
- [ ] 3.2 Update `app/pipeline/ingestion.py` to use `app/paths.py` and implement automatic `TESSDATA_PREFIX` lookup
- [ ] 3.3 Implement build-flavor constant injection in `app/build_config.py` (or similar) via PyInstaller `hook-app.py` or `.spec` logic
- [ ] 3.4 Audit Marker import sites and convert them to guarded lazy imports where needed
- [ ] 3.5 Update Settings UI to gate Pro-only features and display "Standard Edition" vs "Pro Edition" labels

## 4. Installer and docs

- [ ] 4.1 Add `build/installer.iss` with preprocessor defines for Standard/Pro build parameterization
- [ ] 4.2 Add README packaging and install notes for Standard and Pro builds

## 5. Verification

- [ ] 5.1 Verify Standard build: Ensure no `torch` or `marker` files exist in `dist/` and app starts successfully
- [ ] 5.2 Verify Pro build: Ensure `marker` OCR is available and functional on CUDA-enabled systems
- [ ] 5.3 Verify Installer: Run generated setup and confirm shortcuts and registry keys are correct
