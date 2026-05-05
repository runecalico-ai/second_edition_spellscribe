; SpellScribe Windows installer (Inno Setup 6, Unicode).
; Parameterized for Standard vs Pro via preprocessor defines.
;
; Typical invocation (see build/build_all.ps1):
;   iscc /Q /DAppFlavor=Standard /DRepoRoot=C:\path\to\second_edition_spellscribe /DLicenseFile=C:\path\to\resources\license.txt build\installer.iss

#ifndef AppFlavor
  #error "AppFlavor is not defined. Pass /DAppFlavor=Standard or /DAppFlavor=Pro to ISCC (see build/build_all.ps1)."
#endif

#ifndef RepoRoot
  #error "RepoRoot is not defined. Pass /DRepoRoot=<absolute path to the repository root> to ISCC."
#endif

#ifndef LicenseFile
  #error "LicenseFile is not defined. Pass /DLicenseFile=<absolute path to resources\license.txt> to ISCC."
#endif

#if AppFlavor == "Standard"
  #define DistFolder "SpellScribe-Standard"
  #define ExeName "SpellScribe-Standard.exe"
  #define EditionFolder "SpellScribe Standard"
  #define OutputSuffix "Standard"
#elif AppFlavor == "Pro"
  #define DistFolder "SpellScribe-Pro"
  #define ExeName "SpellScribe-Pro.exe"
  #define EditionFolder "SpellScribe Pro"
  #define OutputSuffix "Pro"
#else
  #error "AppFlavor must be exactly Standard or Pro (ISPP compares case-sensitively). Use /DAppFlavor=Standard or /DAppFlavor=Pro."
#endif

#define MyAppName "SpellScribe"
#define MyAppVersion "1.0.0"

[Setup]
#if AppFlavor == "Standard"
AppId={{C3D8F1A6-2E47-5B91-8C0D-7F6E5A4B3C21}}
#elif AppFlavor == "Pro"
AppId={{D4E9A2B7-3F58-6CA2-9D1E-8A7F6B5C4D32}}
#endif
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} ({#OutputSuffix})
UninstallDisplayName={#MyAppName} {#OutputSuffix}
AppPublisher=SpellScribe
DefaultDirName={autopf64}\{#EditionFolder}
DefaultGroupName={#MyAppName} {#OutputSuffix}
LicenseFile={#LicenseFile}
OutputDir={#RepoRoot}\dist\installer
OutputBaseFilename=SpellScribe-{#OutputSuffix}-{#MyAppVersion}-Setup
PrivilegesRequired=admin
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=no
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "launchapp"; Description: "&Launch SpellScribe when setup finishes"; GroupDescription: "When setup completes:"; Flags: unchecked

[Files]
Source: "{#RepoRoot}\dist\{#DistFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName} {#OutputSuffix}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName} {#OutputSuffix}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Tasks: launchapp
