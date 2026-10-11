; The AppId and per-user installation directory remain stable across updates.
#ifndef Payload
  #error Payload is required
#endif
#ifndef Version
  #error Version is required
#endif
#ifndef Output
  #error Output is required
#endif
[Setup]
AppId=io.github.rand0mgg.agentscribe
AppName=AgentScribe
AppVersion={#Version}
AppPublisher=Rand0MGG
DefaultDirName={localappdata}\Programs\AgentScribe
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Output}
OutputBaseFilename=AgentScribe-{#Version}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\AgentScribe.exe

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AgentScribe"; Filename: "{app}\AgentScribe.exe"

[Run]
Filename: "{app}\AgentScribe.exe"; Flags: nowait postinstall skipifsilent
Filename: "{app}\AgentScribe.exe"; Flags: nowait skipifnotsilent; Check: IsApplicationUpdate

[Code]
function IsApplicationUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:AGENTSCRIBEUPDATE|0}') = '1';
end;

function InitializeSetup(): Boolean;
var Attempt: Integer;
begin
  { Never let the installer forcibly close a live recording. The application
    grants WinSparkle shutdown only after data and owned workers are safe. }
  for Attempt := 1 to 100 do begin
    if not CheckForMutexes('AgentScribe.InstallationActive') then Break;
    Sleep(100);
  end;
  Result := not CheckForMutexes('AgentScribe.InstallationActive');
  if not Result then
    MsgBox('请先结束录音并正常退出 AgentScribe，再安装更新。', mbInformation, MB_OK);
end;
