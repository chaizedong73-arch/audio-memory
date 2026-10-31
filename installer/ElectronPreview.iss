#define AppName "Audio Memory Preview"
#define AppVersion "0.1.0"
#ifndef AppDir
  #error Pass /DAppDir with the built Electron app directory
#endif
[Setup]
AppId={{08708B1C-144D-4B0B-B2EA-E9C5458B9980}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AudioMemoryElectronPreview
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\audio-memory-build\electron-preview
OutputBaseFilename=AudioMemory-Electron-INCOMPLETE-Preview-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
UninstallDisplayName={#AppName}
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Audio Memory Preview.exe"
