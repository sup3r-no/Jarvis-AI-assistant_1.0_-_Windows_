; J.A.R.V.I.S. Windows Installer Script
; This script compiles the executable, web files, offline voice model, and dependencies into a Setup Wizard.

[Setup]
; Basic Application Information
AppName=J.A.R.V.I.S.
AppVersion=1.1.0
AppPublisher=Stark Industries (Local)

; Default Installation Folder (C:\Program Files\J.A.R.V.I.S.)
DefaultDirName={autopf}\J.A.R.V.I.S.
; Clean Start Menu group name (No periods)
DefaultGroupName=JARVIS

; Output Settings (Where the final Setup.exe will be saved)
OutputDir=..\Jarvis_Release
OutputBaseFilename=Jarvis_Setup_v1
SetupIconFile=icon.ico

; Compression Settings for a smaller file size
Compression=lzma2/ultra
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

; Aesthetics
WizardStyle=modern
DisableWelcomePage=no

[Dirs]
; Grant write permissions to the installation directory so Jarvis can save bridge scripts & offline models
Name: "{app}"; Permissions: users-modify

[Files]
; 1. The Main Executable
Source: "jarvis_windows.exe"; DestDir: "{app}"; Flags: ignoreversion

; 2. The Custom Icon
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; 3. The Entire Map Directory
Source: "gods-eye-view*"; DestDir: "{app}\gods-eye-view"; Flags: ignoreversion recursesubdirs createallsubdirs

; 4. Offline Vosk Speech Model (Included automatically once generated on your PC)
Source: "vosk-model*"; DestDir: "{app}\vosk-model"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; 5. Bundled Node.js Installer (Extracts to a hidden temp folder and deletes itself after setup)
Source: "node_installer.msi"; DestDir: "{tmp}"; Flags: deleteafterinstall ignoreversion skipifsourcedoesntexist

[Icons]
; Creates a shortcut in the Start Menu
Name: "{group}\J.A.R.V.I.S."; Filename: "{app}\jarvis_windows.exe"; IconFilename: "{app}\icon.ico"

; Creates a shortcut on the Desktop
Name: "{commondesktop}\J.A.R.V.I.S."; Filename: "{app}\jarvis_windows.exe"; IconFilename: "{app}\icon.ico"

[Run]
; SILENTLY installs Node.js if it is missing. /qn means "Quiet No-UI".
Filename: "msiexec.exe"; Parameters: "/i ""{tmp}\node_installer.msi"" /qn"; StatusMsg: "Installing Node.js Backend Environment (This may take a minute)..."; Check: IsNodeMissing; Flags: waituntilterminated

; Gives the user a checkbox to launch Jarvis immediately after installing!
Filename: "{app}\jarvis_windows.exe"; Description: "Launch J.A.R.V.I.S. now"; Flags: nowait postinstall skipifsilent

[Code]
// Custom function to check if Node.js is missing
function IsNodeMissing(): Boolean;
begin
// Returns TRUE if Node is missing AND node_installer.msi was bundled
Result := FileExists(ExpandConstant('{tmp}\node_installer.msi')) and not (RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\Node.js') or RegKeyExists(HKEY_CURRENT_USER, 'SOFTWARE\Node.js'));
end;

// This section runs when the user double-clicks the Setup.exe file
function InitializeSetup(): Boolean;
var
BlenderInstalled: Boolean;
ErrorCode: Integer;
begin
Result := True; // Allow the setup to continue regardless

// Bulletproof Blender Check (Searches App Paths, File Associations, and multiple registry locations)
BlenderInstalled :=
RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\blender.exe') or
RegKeyExists(HKEY_CURRENT_USER, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\blender.exe') or
RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\Blender Foundation') or
RegKeyExists(HKEY_CURRENT_USER, 'SOFTWARE\Blender Foundation') or
RegKeyExists(HKEY_CLASSES_ROOT, '.blend');

// We only warn about Blender now. Node.js is handled automatically!
if not BlenderInstalled then
begin
if MsgBox('J.A.R.V.I.S. works best with Blender 3D installed (Required for AI 3D Mesh Generation).' + #13#10#13#10 + 'Would you like to open the official download page for Blender now?', mbConfirmation, MB_YESNO) = IDYES then
begin
ShellExec('open', 'https://www.blender.org/download/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;
end;
end;