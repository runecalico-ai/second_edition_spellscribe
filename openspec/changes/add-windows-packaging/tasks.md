## Sequencing

- Implement last, after all runtime changes are in place.
- Freeze only after the shell, pipeline, settings, and export behavior are stable enough to package and smoke-test.

## 1. Build specs

- [ ] 1.1 Add `build/spell_scribe_std.spec` with Standard-build datas, hidden imports, and excludes
- [ ] 1.2 Add `build/spell_scribe_pro.spec` with the Pro-build dependency set and shared resources

## 2. Frozen runtime behavior

- [ ] 2.1 Update runtime startup code to configure bundled Tesseract and `TESSDATA_PREFIX` in frozen mode
- [ ] 2.2 Audit Marker import sites and convert them to guarded lazy imports where needed

## 3. Installer and docs

- [ ] 3.1 Add `build/installer.iss` for Windows installation output
- [ ] 3.2 Add README packaging and install notes for Standard and Pro builds
