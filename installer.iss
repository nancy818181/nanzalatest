#define MyAppName "Nanza Accounting"
#define MyAppVersion "2.9.114"
#define MyAppPublisher "Saber for Audit"

[Setup]
AppId={{4C848D44-EF69-47C0-86F1-5A5AA3C34E8D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
; 2.9.114: new installations go to "Nanza Accounting"; an installed copy keeps its folder (same AppId)
DefaultDirName={autopf}\Nanza Accounting
DefaultGroupName=Nanza Accounting
DisableProgramGroupPage=yes
OutputDir=installer-output
OutputBaseFilename=NanzaAccountingSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=Assets\nanza.ico
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\nanza.ico
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; Close a running copy before upgrading. Company data lives in the user's
; SaberAccounting folder and is never touched by install, upgrade or uninstall.
CloseApplications=yes
RestartApplications=no

[Tasks]
; On by default (owner request, 2.9.36): daily background backup of every company and year with Windows. Untick to rely only on the backup made when a company is opened.
Name: "autobackup"; Description: "Start automatic daily backups with Windows (all companies and years)"

[Files]
; The application is built with PyInstaller --onedir, so the program lives in
; dist\NanzaAccounting\ (NanzaAccounting.exe plus its _internal support files).
; Package the whole folder; NanzaAccounting.exe lands at {app}\NanzaAccounting.exe (2.9.114: was SaberAccounting.exe).
Source: "dist\NanzaAccounting\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\NanzaAccountingBackup.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Assets\Saber_for_Audit_logo.png"; DestDir: "{app}\assets"; Flags: ignoreversion
; 2.9.57: the Saber icon for the shortcuts, the window and Add / Remove Programs (no workflow change needed)
Source: "Assets\saber.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "Assets\nanza.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "Assets\nanza_logo.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "Assets\nanza_icon.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "Assets\fonts\Amiri-OFL.txt"; DestDir: "{app}\assets\fonts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Nanza Accounting"; Filename: "{app}\NanzaAccounting.exe"; IconFilename: "{app}\nanza.ico"
Name: "{autodesktop}\Nanza Accounting"; Filename: "{app}\NanzaAccounting.exe"; IconFilename: "{app}\nanza.ico"
Name: "{commonstartup}\Nanza Accounting Backups"; Filename: "{app}\NanzaAccountingBackup.exe"; WorkingDir: "{app}"; Tasks: autobackup; Check: FileExists(ExpandConstant('{app}\NanzaAccountingBackup.exe'))

[Run]
; 2.9.87: the background backup starts again with the new version (it was stopped before the files were replaced)
Filename: "{app}\NanzaAccountingBackup.exe"; WorkingDir: "{app}"; Flags: nowait runhidden skipifdoesntexist; Tasks: autobackup
Filename: "{app}\NanzaAccounting.exe"; Description: "Open Nanza Accounting"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM NanzaAccountingBackup.exe"; Flags: runhidden; RunOnceId: "StopBackup"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM NanzaAccounting.exe"; Flags: runhidden; RunOnceId: "StopNanza"

[Code]
// 2.9.87: the background backup program (started with Windows) kept SaberAccountingBackup.exe and the data files
// in use, so the setup could not replace it ("file in use" / the setup stuck). Both programs are stopped first;
// the company data is never touched.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM NanzaAccountingBackup.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM NanzaAccounting.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  // 2.9.114: the programs had the old names before this version - stop those too
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM SaberAccountingBackup.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM SaberAccounting.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1500);
  Result := '';
end;

[InstallDelete]
; 2.9.111: the product is now named Nanza - remove the old "Saber Accounting" and "Mizan Accounting" shortcuts
Type: files; Name: "{autoprograms}\Saber Accounting.lnk"
Type: files; Name: "{autodesktop}\Saber Accounting.lnk"
Type: files; Name: "{autoprograms}\Mizan Accounting.lnk"
Type: files; Name: "{autodesktop}\Mizan Accounting.lnk"
; 2.9.114: the program files are renamed NanzaAccounting.exe / NanzaAccountingBackup.exe - remove the old ones
; and the old "Saber Accounting Backups" start-up shortcut (the company data is never touched)
Type: files; Name: "{app}\SaberAccounting.exe"
Type: files; Name: "{app}\SaberAccountingBackup.exe"
Type: files; Name: "{commonstartup}\Saber Accounting Backups.lnk"
