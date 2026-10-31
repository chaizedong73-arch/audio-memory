#define AppName "AI 录音记忆（开发预览版）"
#define AppVersion "0.1.0"
#ifndef RuntimeDir
  #error Pass /DRuntimeDir with the bundled Python runtime directory
#endif
#ifndef ModelDir
  #error Pass /DModelDir with the offline base model directory
#endif

[Setup]
AppId={{877CF3A9-AAD6-4F2B-81E8-0F5D98A795B3}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AudioMemoryPreview
DefaultGroupName=AI Audio Memory Preview
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AudioMemory-Internal-Migration
Compression=none
SolidCompression=no
WizardStyle=modern
CloseApplications=no
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#RuntimeDir}\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ModelDir}\*"; DestDir: "{app}\models\asr\base"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs
Source: "..\annotation_worker.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\archive.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\asr_visual_context.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\classroom_material_db.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\classroom_session_bridge.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\cloud_asr_trial.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\context_auto.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\context_candidate_generator.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\extract_loop.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\extract_memory.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\health.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\live.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\migrate_out.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\miniob_material_export.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pipeline.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\play.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ppt_concepts.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ppt_locator.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\prepare_visual_models.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_asr.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scene_capture.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scene_usb.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scene_wifi.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\speak_label.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\speaker_cluster.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\speaker_id.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\speaker_tag.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\subs_one.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\subtitle_decisions.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\subtitle_maintenance.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_benchmark.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_experiment.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_lab.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_vocabulary_schema.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_vocabulary_test.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\winctx.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_core.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\recorder.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\transcriber.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\singlelock.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\material_bridge.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\material_store.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\transcript_corrections.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\transcript_quality.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\classroom_materials.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\classroom_mode.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ai_material_gateway.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\notes_maintenance.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\video_unit.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\video_slides.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ppt_keyframes.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ocr_unit.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ppt_ocr.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual_worker.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\time_alignment_unit.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\module_launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\control-panel.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\control.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements-core.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements-vision.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\hotwords.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\start.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\gateway.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\visual.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\视觉功能单元协议.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\材料桥接协议.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AI 录音记忆（开发预览版）"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File ""{app}\control-panel.ps1"""; WorkingDir: "{app}"
Name: "{autodesktop}\AI 录音记忆（开发预览版）"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File ""{app}\control-panel.ps1"""; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    if not Exec(ExpandConstant('{app}\runtime\python.exe'), '"' + ExpandConstant('{app}\material_store.py') + '"', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
      MsgBox('无法初始化资料库。已有数据已保留。', mbError, MB_OK);
      Abort;
    end;
    if ResultCode <> 0 then begin
      MsgBox('资料库初始化失败。已有数据已保留。', mbError, MB_OK);
      Abort;
    end;
  end;
end;

