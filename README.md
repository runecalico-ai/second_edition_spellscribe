# SpellScribe (second edition)

Desktop tooling for extracting and reviewing structured spell data from documents. This repository targets Windows packaging via PyInstaller and Inno Setup.

## Windows packaging

### Prerequisites

On the machine that runs the build:

1. **Python 3.12** with a virtual environment activated. Keep that same venv active for the whole build so `pyinstaller` resolves to the interpreter that has your installed dependencies (`Get-Command pyinstaller` should point inside `.venv`).
2. **Project dependencies**: `pip install -r requirements.txt` (from the repo root).
3. **PyInstaller** available on `PATH` (the build script invokes `pyinstaller` directly).
4. **Inno Setup 6.3 or newer** with `iscc.exe` on `PATH` (used to compile `build/installer.iss`; `installer.iss` uses `ArchitecturesAllowed=x64compatible`, which requires 6.3+). Official builds: [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php).
5. **Tesseract OCR** on the build host: `build/build_all.ps1` currently resolves **5.5.x** with **`eng.traineddata`** next to the resolved `tesseract.exe` (see `Resolve-TesseractBundleInputs` for search paths: common install dirs, `PATH`, registry under `Tesseract-OCR`). If your machine differs, update the script’s version gate or install a matching Tesseract build before packaging.

Optional: enable **`-RequireTrustedTesseract`** if you need the detected `tesseract.exe` to have a valid Authenticode signature on Windows.

### Build commands

From the repository root, run **PowerShell 7+** (`pwsh`):

```powershell
pwsh build/build_all.ps1 -Flavor Standard
pwsh build/build_all.ps1 -Flavor Pro
pwsh build/build_all.ps1 -Flavor All
```

Useful flags (see `build/build_all.ps1` for full behavior):

| Flag | Purpose |
|------|---------|
| `-ProbeOnly` | Resolve Tesseract, icon, and license paths; print summary; **no** PyInstaller or installer build. |
| `-SkipPyInstaller` | Skip frozen app builds (useful when iterating on the installer only). **Requires** an existing populated `dist/SpellScribe-Standard/` or `dist/SpellScribe-Pro/` from a prior PyInstaller run; otherwise `iscc` fails because `[Files]` has nothing to pack. |
| `-SkipInstaller` | Skip Inno Setup (`iscc`) even when the script is present. |
| `-RequireInstaller` | Fail the script if the installer step cannot run (for example `iscc` missing); incompatible with `-SkipInstaller`. |
| `-RequireTrustedTesseract` | Require a trusted Authenticode signature for the chosen `tesseract.exe` on Windows. |
| `-Clean` | Pass `--clean` through to PyInstaller. |
| `-DryRun` | Print external commands without executing them. |

The installer compiler is invoked like (build script also passes `/Q` for a quiet compile):

`iscc /Q "/DAppFlavor=Standard" "/DRepoRoot=C:\absolute\path\to\second_edition_spellscribe" "/DLicenseFile=C:\absolute\path\to\second_edition_spellscribe\resources\license.txt" build\installer.iss`

`LicenseFile` and `RepoRoot` must be **absolute** paths (see `build/installer.iss` and `build/build_all.ps1`). When you run **`build/build_all.ps1` from PowerShell**, each `/D…=…` value is passed to `iscc` as a **single argument**, so repository paths that contain spaces (for example under `OneDrive\…`) remain valid without extra shell quoting. For **manual** `cmd.exe` invocations, keep the `/D…="C:\path with spaces\…"` form shown above.

### Output locations

| Artifact | Path |
|----------|------|
| Standard onedir bundle | `dist/SpellScribe-Standard/` (main executable `SpellScribe-Standard.exe`) |
| Pro onedir bundle | `dist/SpellScribe-Pro/` (main executable `SpellScribe-Pro.exe`) |
| Setup programs | `dist/installer/` — e.g. `SpellScribe-Standard-1.0.0-Setup.exe`, `SpellScribe-Pro-1.0.0-Setup.exe` (version segment comes from `MyAppVersion` in `build/installer.iss`) |

`AppVerName` / `OutputBaseFilename` use installer metadata `#define MyAppVersion` (`1.0.0` today) inside `build/installer.iss`. The running app and JSON export use `app/__init__.py` `__version__` — keep both in sync when you cut a release so filenames, uninstall metadata, and exported `spellscribe_version` agree.

### Troubleshooting

- **`iscc` “Source file not found” / empty archive**: the matching `dist/SpellScribe-*` onedir is missing or empty. Run PyInstaller first (omit `-SkipPyInstaller`) or restore the folder from a prior build.
- **Stale junk bundled into setup**: delete or rebuild the flavor output under `dist/` before a release compile so `[Files]` only picks up the fresh onedir.
- **Interrupted upgrade / odd runtime mix**: the installer uses `ignoreversion` on the PyInstaller tree so every file is replaced on reinstall. If an install is corrupted, uninstall from Settings → Apps or delete the per-flavor folder under `%ProgramFiles%`, then reinstall.
- **Installer cannot overwrite running EXE**: quit SpellScribe (and let the Inno “applications using files” step close handles) before upgrading; `CloseApplications=yes` is enabled in `build/installer.iss`.
- **SmartScreen “Windows protected your PC”**: expected for unsigned `Setup.exe` until you attach an Authenticode `SignTool` step (see Inno Setup docs) or reputation accrues for your publisher.

### Standard vs Pro

| | **Standard** | **Pro** |
|---|--------------|---------|
| **Bundle size** | Smaller: Marker, PyTorch, and related heavy stacks are excluded. | Larger: includes Marker and GPU-oriented runtime stack. |
| **OCR / ML** | Tesseract-focused workflow; Marker/GPU OCR options are not available in the Standard build. | Marker-based OCR path available where supported (typically CUDA-capable systems for GPU acceleration). |
| **Runtime label** | Standard edition branding in the app. | Pro edition branding in the app. |

### Automated packaging checks

After `build/build_all.ps1` produces artifacts, run:

```powershell
pwsh build/verify_packaging.ps1 -Checks All          # warn if dist folders missing (default non-strict)
pwsh build/verify_packaging.ps1 -Checks Standard -Strict   # fail if Standard dist missing or contains marker/torch paths
pwsh build/verify_packaging.ps1 -Checks Pro -Strict
pwsh build/verify_packaging.ps1 -Checks Installer -Strict
pwsh build/verify_packaging.ps1 -Checks Standard -SmokeExe  # launch Standard exe briefly (closes/kills process)
```

`-Strict` turns missing `dist/` trees (and missing installer outputs when that check runs) into hard failures. Without `-Strict`, missing **selected** outputs (Standard onedir, Pro onedir, or installer payloads, depending on `-Checks`) log warnings instead of throwing—except `-SmokeExe` still requires the target `.exe` to exist (non-strict skips smoke with a warning when the bundle is absent). `-SmokeExe` is best-effort: the script stops the root process only, so GUI child processes may survive—prefer disposable hosts for repeated smokes.

The Standard scan matches the heavy-stack excludes from `build/spell_scribe_std.spec` (path segments for `marker`, `marker_pdf`, `torch`, `torchvision`, `torchaudio`, `transformers`, `accelerate`, `onnxruntime`, `sentence_transformers`, plus `torch_*.dll` under `_internal`). It is still a heuristic—do not treat it as a substitute for full binary audits when threat modeling the bundle.

### Manual smoke checks

**Pro build — Marker / CUDA (release verification)**

- Install or run from `dist/SpellScribe-Pro/SpellScribe-Pro.exe` on a machine with a supported NVIDIA stack if you rely on CUDA.
- Confirm the Pro onedir actually contains Marker/Torch artifacts (`build/verify_packaging.ps1 -Checks Pro -Strict` performs a path-level check).
- In **Settings**, confirm Pro-only OCR options (Marker / GPU) are visible. **End-to-end Marker OCR in the ingestion pipeline is still gated on future `ocr_backend` wiring in `route_document`;** until then, treat CUDA/Marker validation as “GPU stack loads / smoke PDF with planned behavior,” not a guarantee that Settings switches change OCR engines.

**Installer — shortcuts and “Programs and Features” (release verification)**

- Run the generated `dist/installer/SpellScribe-*-Setup.exe` (for example `SpellScribe-Standard-1.0.0-Setup.exe`) elevated (installer uses per-machine `Program Files (x64)`).
- After install, confirm a **Start Menu** shortcut under the flavor-specific program group opens the correct `SpellScribe-Standard.exe` or `SpellScribe-Pro.exe` from the install directory.
- Optionally enable the **desktop shortcut** task during setup and confirm it targets the same executable.
- In **Windows Settings → Apps → Installed apps** (or **Control Panel → Programs and Features**), confirm **SpellScribe** appears as a **separate** entry for Standard vs Pro (distinct `AppId` / uninstall records), with the expected display name and install location under `%ProgramFiles%` (for example `SpellScribe Standard` vs `SpellScribe Pro`).
