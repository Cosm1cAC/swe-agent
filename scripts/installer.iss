; Mini SWE CLI — Inno Setup 安装脚本
; 安装 swe-cli.exe 到用户目录并自动配置 PATH

#define MyAppName "Mini SWE CLI"
#define MyAppShortName "swe-cli"
#define MyAppPublisher "Z.ai"
#define MyAppVersion "0.1.0"
#define MyAppURL "https://github.com/Cosm1cAC/swe-agent"
#define MyAppExeName "swe-cli.exe"

[Setup]
AppId={{A3B8E9F1-2C4D-5E6F-7A8B-9C0D1E2F3A4B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputBaseFileName=Install-swe-cli-{#MyAppVersion}
OutputDir=..\dist
SetupIconFile=
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
; 不需要管理员权限——安装在用户目录
PrivilegesRequired=lowest
; 支持 Windows 7 及以上
MinVersion=6.1
; 让用户可以选择安装位置
DirExistsWarning=no
LanguageDetectionMethod=locale

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; Flags: nowait postinstall skipifsilent

; ───────────────────────────────────────────────
; Code 段：自动配置用户 PATH
; ───────────────────────────────────────────────

[Code]

{ 检查 AppDir 是否已在用户 PATH 中 }
function IsDirInPath(const AppDir: string): Boolean;
var
  PathStr: string;
  SearchStr: string;
  P: Integer;
begin
  Result := False;
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', PathStr) then
    Exit;

  { 统一转小写比较 }
  SearchStr := LowerCase(AppDir);
  PathStr := LowerCase(PathStr);

  { 检查是否以 AppDir; 开头 }
  if Copy(PathStr, 1, Length(AppDir) + 1) = SearchStr + ';' then
  begin
    Result := True;
    Exit;
  end;

  { 检查 ;AppDir; 或 ;AppDir\ 结尾 }
  if Pos(';' + SearchStr + ';', PathStr) > 0 then
  begin
    Result := True;
    Exit;
  end;

  { 检查结尾（无分号）}
  if PathStr = SearchStr then
  begin
    Result := True;
    Exit;
  end;
end;

{ 将 AppDir 添加到用户 PATH（注册表 HKCU\Environment）}
procedure AddToUserPath(const AppDir: string);
var
  PathStr: string;
  NewPath: string;
begin
  if IsDirInPath(AppDir) then
  begin
    Log('PATH already contains: ' + AppDir);
    Exit;
  end;

  { 读取当前用户 PATH }
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', PathStr) then
    PathStr := '';

  { 追加到前面（确保优先查找）}
  if PathStr = '' then
    NewPath := AppDir
  else
    NewPath := AppDir + ';' + PathStr;

  { 写回注册表（REG_EXPAND_SZ 类型以保留 %XXX% 变量）}
  if RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', NewPath) then
  begin
    SendBroadcastMessage('WM_SETTINGCHANGE', 0, 0);
    Log('PATH updated: ' + NewPath);
  end
  else
    Log('Failed to update PATH with RegWriteExpandStringValue, trying RegWriteStringValue...');
    { 回退：用 REG_SZ 写入 }
    if RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', NewPath) then
    begin
      SendBroadcastMessage('WM_SETTINGCHANGE', 0, 0);
      Log('PATH updated (as REG_SZ): ' + NewPath);
    end
    else
      Log('Failed to update PATH');
end;

{ 从用户 PATH 中移除 AppDir }
procedure RemoveFromUserPath(const AppDir: string);
var
  PathStr: string;
  NewPath: string;
  SearchStr: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', PathStr) then
    Exit;

  NewPath := PathStr;
  SearchStr := AppDir;

  { 移除 "AppDir;" （开头）}
  if Copy(NewPath, 1, Length(SearchStr) + 1) = SearchStr + ';' then
    Delete(NewPath, 1, Length(SearchStr) + 1);

  { 移除 ";AppDir;" }
  P := Pos(';' + SearchStr + ';', NewPath);
  if P > 0 then
    Delete(NewPath, P, Length(SearchStr) + 2);

  { 移除 ";AppDir" （结尾）}
  if Length(NewPath) >= Length(SearchStr) + 1 then
  begin
    P := Length(NewPath) - Length(SearchStr);
    if Copy(NewPath, P, Length(SearchStr) + 1) = ';' + SearchStr then
      Delete(NewPath, P, Length(SearchStr) + 1);
  end;

  { 如果只剩 AppDir（没有分号）}
  if NewPath = SearchStr then
    NewPath := '';

  { 写回 }
  if NewPath = '' then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Environment', 'PATH');
    Log('PATH deleted');
  end
  else
  begin
    if RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', NewPath) then
      Log('PATH cleaned: ' + NewPath)
    else
      RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'PATH', NewPath);
  end;

  SendBroadcastMessage('WM_SETTINGCHANGE', 0, 0);
end;

{ 安装后自动添加 PATH }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    Log('Adding ' + ExpandConstant('{app}') + ' to user PATH...');
    AddToUserPath(ExpandConstant('{app}'));
  end;
end;

{ 卸载时自动清理 PATH }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Log('Removing ' + ExpandConstant('{app}') + ' from user PATH...');
    RemoveFromUserPath(ExpandConstant('{app}'));
  end;
end;
