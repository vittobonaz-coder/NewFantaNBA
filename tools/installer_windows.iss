; Installer dell'app Windows (Inno Setup 6, Fase 5, docs/fase5_piano.md). Lo lancia tools\build_windows.ps1 -Installer:
;   ISCC.exe /DAppVersion=1.0.0 /DSourceDir=<build\windows> /DOutputDir=<build\dist> tools\installer_windows.iss
; Solo per l'utente (niente amministratore), in %LOCALAPPDATA%\Programs\Bonkest. AppId fisso: un nuovo
; Bonkest-Setup.exe aggiorna sopra la versione precedente. I dati (%APPDATA%\Bonkest) non si toccano mai.

#ifndef AppVersion
  #error Manca /DAppVersion
#endif
#ifndef SourceDir
  #error Manca /DSourceDir
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
; Non cambiare mai AppId: è ciò che fa riconoscere a Windows l'installazione precedente
AppId={{6E1B7C64-2B1F-4E0B-9C1D-B0B0C5E5A001}
AppName=Bonkest
AppVersion={#AppVersion}
AppVerName=Bonkest {#AppVersion}
AppPublisher=Bonkest
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Bonkest
DefaultGroupName=Bonkest
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Bonkest-Setup
UninstallDisplayIcon={app}\bonkest.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tutta la cartella del build; i file di una versione precedente non più presenti vengono tolti da [InstallDelete]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Aggiornamento pulito: via il codice della versione precedente (i dati stanno in %APPDATA%, non qui)
Type: filesandordirs; Name: "{app}\*"

[Icons]
Name: "{group}\Bonkest"; Filename: "{app}\bonkest.exe"
Name: "{userdesktop}\Bonkest"; Filename: "{app}\bonkest.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\bonkest.exe"; Description: "{cm:LaunchProgram,Bonkest}"; Flags: nowait postinstall skipifsilent
