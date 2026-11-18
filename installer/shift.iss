; Inno Setup script for Shift.  Build:  ISCC.exe /DAppVersion=1.4.0 installer\shift.iss
; Installs per user (no admin rights) into %LOCALAPPDATA%\Programs\Shift,
; so Shift can keep updating itself.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise Shift for updates and uninstalling.
AppId={{6E0D3B5C-4A7F-4E52-9C1B-8F2A7D9E4C31}
AppName=Shift
AppVersion={#AppVersion}
AppVerName=Shift {#AppVersion}
AppPublisher=Ambulant-biv
AppPublisherURL=https://ambulant-biv.github.io/Shift/
AppSupportURL=https://github.com/Ambulant-biv/Shift/issues
AppUpdatesURL=https://github.com/Ambulant-biv/Shift/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Shift
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ShiftSetup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Shift.exe
UninstallDisplayName=Shift
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Shift.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Shift"; Filename: "{app}\Shift.exe"
Name: "{autodesktop}\Shift"; Filename: "{app}\Shift.exe"; Tasks: desktopicon
Name: "{usersendto}\Shift"; Filename: "{app}\Shift.exe"

[InstallDelete]
; leftovers from the old manual install and earlier names of the app
Type: files; Name: "{app}\Shift.update.exe"
Type: files; Name: "{userdesktop}\Wissel.lnk"
Type: files; Name: "{userdesktop}\Bestandsomzetter.lnk"
Type: files; Name: "{usersendto}\Shift.lnk"
Type: files; Name: "{usersendto}\Wissel.lnk"
Type: files; Name: "{usersendto}\Bestandsomzetter.lnk"

[Run]
Filename: "{app}\Shift.exe"; Description: "{cm:LaunchProgram,Shift}"; Flags: nowait postinstall skipifsilent
