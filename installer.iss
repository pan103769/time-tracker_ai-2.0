; installer.iss — Inno Setup Script for Time Tracker AI 2
; Compiles the standalone packaged distribution into a production Windows installer.

#define MyAppName "Time Tracker AI"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Time Tracker AI Team"
#define MyAppURL "https://github.com/pant/time-tracker-ai"
#define MyAppExeName "TimeTrackerAI.exe"

[Setup]
AppId={{C6B5F482-1D45-4B81-8B39-9B9481DF4B6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=TimeTrackerAI_Setup_v2.0.0
SetupIconFile=assets\time_tracker_ai.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Automatically launch Time Tracker AI at Windows startup"; GroupDescription: "Startup options:"; Flags: unchecked

[Files]
Source: "dist\TimeTrackerAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Note: User data is stored in %APPDATA%\TimeTrackerAI, never in Program Files.

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\time_tracker_ai.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\time_tracker_ai.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Registry]
; Register custom URI protocol timetracker://
Root: HKCU; Subkey: "Software\Classes\timetracker"; ValueType: string; ValueName: ""; ValueData: "URL:Time Tracker AI Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\timetracker"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\timetracker\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\_internal\assets\time_tracker_ai.ico"",0"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\timetracker\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
