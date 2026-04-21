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
The packaged app SHALL configure both the Tesseract executable path and the tessdata root in frozen mode.

#### Scenario: Frozen runtime sets executable and tessdata paths
- **WHEN** the app starts in a PyInstaller-frozen environment
- **THEN** it sets `pytesseract.pytesseract.tesseract_cmd` and `TESSDATA_PREFIX` to the bundled Tesseract paths

### Requirement: The project provides a Windows installer
The system SHALL provide an Inno Setup installer for the packaged app.

#### Scenario: Installer creates app shortcut
- **WHEN** the user installs SpellScribe from the generated setup program
- **THEN** the installer creates the configured Start Menu shortcut
