; LEAF Windows installer (Inno Setup).
;
; Expects the PyInstaller onedir build of the launcher plus the bundled
; portable-Python runtime archive and version pin to already be staged in
; dist\LEAF\ before this script runs. Build order:
;
;   1. pyinstaller packaging\launcher\leaf_launcher.spec --distpath dist --workpath build\launcher
;   2. python packaging\runtime\fetch_python.py windows-amd64 --out dist\LEAF
;   3. echo leaf-framework==<version> > dist\LEAF\leaf-framework.version
;   4. ISCC packaging\windows\leaf.iss
;
; Output: packaging\windows\Output\LEAF-Setup-<arch>.exe -- matching the
; arch-tagged naming already used for macOS (LEAF-macos-<arch>.dmg) and
; Linux (LEAF-linux-<arch>.AppImage), so a future second Windows arch
; build doesn't silently overwrite this one's release asset.
;
#define MyAppName "LEAF"
#define MyAppPublisher "Systems Biology, Wageningen University & Research"
#define MyAppURL "https://leaf-framework.org"
#define MyAppExeName "LEAF.exe"
#define SourceDir "..\..\dist\LEAF"
#define MyAppVersion GetEnv("LEAF_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0"
#endif
#define MyAppArch GetEnv("LEAF_WIN_ARCH")
#if MyAppArch == ""
  #define MyAppArch "amd64"
#endif

[Setup]
AppId={{6C6C1B0A-6B7B-4D8D-9C5B-9B7B6B0F6A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Per-user install by default so no admin prompt is needed for a clickable app.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=LEAF-Setup-{#MyAppArch}
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\..\leaf\ui\images\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
; Signs the setup and the uninstaller inside it with the "leafsign" tool,
; which the CI job defines (ISCC /Sleafsign=...). Local builds stay unsigned.
#if GetEnv("LEAF_SIGN") == "true"
SignTool=leafsign
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; LEAF's venv + downloaded portable runtime live outside {app} (in %LOCALAPPDATA%\LEAF),
; so a normal uninstall leaves them for a fast reinstall. Users who want a full wipe
; can delete %LOCALAPPDATA%\LEAF manually; we deliberately don't do it for them here.
