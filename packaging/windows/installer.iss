; The AppId and per-user installation directory remain stable across updates.
#if VER < EncodeVer(7, 0, 0)
  #error Inno Setup 7 is required to preserve complete long-path license files.
#endif
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

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Previous: String;
begin
  Result := '';
  if CheckForMutexes('AgentScribe.InstallationActive') then begin
    Result := '请先结束录音并正常退出 AgentScribe，再安装更新。';
    Exit;
  end;
  { Keep the existing JSON inventory, including after an interrupted retry.
    User data and the updater's verified old-program backup are not touched. }
  Previous := ExpandConstant('{app}\.agentscribe-previous-build.json');
  if FileExists(ExpandConstant('{app}\build-manifest.json')) and not FileExists(Previous) then
    if not FileCopy(ExpandConstant('{app}\build-manifest.json'), Previous, True) then
      Result := '无法保留旧程序清单；未开始安装，请检查目录权限。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Previous, Parameters: String;
begin
  if CurStep = ssPostInstall then begin
    Previous := ExpandConstant('{app}\.agentscribe-previous-build.json');
    Parameters := '--python -m linguaflow.windows_install_cleanup --previous "' + Previous + '"';
    { Use the new, already copied runtime. It reads both manifests with stdlib
      only; failure stops relaunch and leaves the old inventory for retry. }
    if not Exec(ExpandConstant('{app}\AgentScribe.exe'), Parameters,
                ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('新版程序无法验证；请保留旧版恢复材料，重试安装。');
    if Code <> 0 then
      RaiseException('旧程序文件清理未完成；已保留清单与恢复材料，请检查目录后重试。');
  end;
end;
