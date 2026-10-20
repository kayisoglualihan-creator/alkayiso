; Inno-Setup-Skript für den JARVIS-Windows-Installer (Installation pro Benutzer, keine Admin-Rechte nötig).
; Bauen:  ISCC.exe installers\jarvis.iss   (vorher: pyinstaller installers\jarvis.spec)
#define AppName "J.A.R.V.I.S."
#define AppVersion "0.4.0"

[Setup]
AppId={{6C1B0F63-6E52-4C2B-9D57-1A4D1B7A6A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=JARVIS
DefaultDirName={localappdata}\Programs\JARVIS
DefaultGroupName=JARVIS
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=JARVIS-Setup-{#AppVersion}
SetupIconFile=jarvis.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "autostart"; Description: "Jarvis beim Windows-Login automatisch starten"; GroupDescription: "Optionen:"
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Optionen:"

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; Optional: native Flutter-Desktop-App (falls gebaut)
Source: "..\apps\jarvis_app\build\windows\x64\runner\Release\*"; DestDir: "{app}\desktop-app"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\documentation\*"; DestDir: "{app}\documentation"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\tailscale_serve.ps1"; DestDir: "{app}\scripts"

[Icons]
Name: "{group}\JARVIS"; Filename: "{app}\JARVIS.exe"; Parameters: "--tray"
Name: "{group}\JARVIS Diagnose"; Filename: "{app}\JARVIS.exe"; Parameters: "--diagnose"
Name: "{group}\Tailscale Serve einrichten"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\tailscale_serve.ps1"""
Name: "{group}\Dokumentation"; Filename: "{app}\documentation"
Name: "{userdesktop}\JARVIS"; Filename: "{app}\JARVIS.exe"; Parameters: "--tray"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JARVIS"; ValueData: """{app}\JARVIS.exe"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\JARVIS.exe"; Parameters: "--tray"; Description: "JARVIS jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
function TailscaleInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\Tailscale\tailscale.exe')) or FileExists(ExpandConstant('{commonpf}\Tailscale\tailscale.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not TailscaleInstalled()) then
    MsgBox('Hinweis: Tailscale ist nicht installiert. Für den sicheren Zugriff vom iPhone wird Tailscale benötigt:' + #13#10 +
           'https://tailscale.com/download/windows' + #13#10#13#10 +
           'Jarvis funktioniert am PC auch ohne Tailscale.', mbInformation, MB_OK);
end;
