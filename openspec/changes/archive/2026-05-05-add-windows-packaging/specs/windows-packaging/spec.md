## ADDED Requirements

### Requirement: The project provides separate Standard and Pro Windows builds
The system SHALL provide separate Standard and Pro PyInstaller build configurations.

#### Scenario: Standard build excludes heavy ML stack
- **WHEN** the project builds the Standard Windows package
- **THEN** the build excludes Marker, Torch, Torchvision, Transformers, and Accelerate

#### Scenario: Pro build keeps Marker stack
- **WHEN** the project builds the Pro Windows package
- **THEN** the build includes the Marker and PyTorch runtime stack required by the revised spec

### Requirement: Standard packaging depends on lazy Marker imports
The runtime code SHALL import Marker lazily so the Standard build does not bundle the heavy dependency stack unintentionally.

#### Scenario: Marker import stays inside guarded runtime path
- **WHEN** the Standard build is analyzed by PyInstaller
- **THEN** the runtime code does not force the Marker stack into the package through eager imports

### Requirement: Frozen runtime configures bundled Tesseract correctly
The packaged app SHALL configure both the Tesseract executable path and the tessdata root in frozen mode via centralized logic in `app/paths.py`.

#### Scenario: Frozen runtime sets executable and tessdata paths
- **WHEN** the app starts in a PyInstaller-frozen environment
- **THEN** it sets `pytesseract.pytesseract.tesseract_cmd` and `TESSDATA_PREFIX` using the bundled paths resolved in `app/paths.py`

#### Scenario: Custom Tesseract path uses automatic tessdata lookup
- **WHEN** the user provides a custom Tesseract executable path in Settings
- **THEN** the system automatically searches for a `tessdata/` folder in the same directory or parent directory to set `TESSDATA_PREFIX`

### Requirement: The app identifies its build flavor at runtime
The system SHALL use a build-time injected constant to distinguish between Standard and Pro versions.

#### Scenario: Standard build disables Pro-only features
- **WHEN** the app is running in a Standard build
- **THEN** the Settings UI hides or disables the "Marker/GPU" OCR option and labels the version as "Standard Edition"

### Requirement: The project provides a Windows installer
The system SHALL provide a single Inno Setup installer script that supports both Standard and Pro builds via preprocessor defines. The script relies on Inno Setup **6.3 or newer** (for example `ArchitecturesAllowed=x64compatible`).

#### Scenario: Installer preprocessor uses exact flavor tokens
- **WHEN** the packaging maintainer compiles `build/installer.iss`
- **THEN** the `AppFlavor` define passed to Inno Setup SHALL be exactly `Standard` or `Pro` (case-sensitive ISPP comparison), matching the values emitted by `build/build_all.ps1`

#### Scenario: Installer creates app shortcut
- **WHEN** the user installs SpellScribe from the generated setup program
- **THEN** the installer creates the configured Start Menu shortcut and installs the files for the selected build flavor

#### Scenario: Installer compilation consumes the PyInstaller onedir output
- **WHEN** the packaging maintainer compiles `build/installer.iss` for a given flavor
- **THEN** the Inno `[Files]` source tree for that flavor is the matching `dist/SpellScribe-<Standard|Pro>/` onedir produced by PyInstaller (installer-only workflows must reuse an existing onedir or rebuild it first)

#### Scenario: Standard and Pro installers register as separate products
- **WHEN** both Standard and Pro installers are produced from the same script using different preprocessor flavors
- **THEN** each build uses a distinct stable `AppId` and flavor-specific default install directory under 64-bit Program Files so Windows shows separate uninstall entries per edition
