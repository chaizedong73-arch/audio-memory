param([Parameter(Mandatory=$true)][string]$fixture,[string]$HostRoot=(Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'),[string]$ProgramRoot=(Split-Path $PSScriptRoot -Parent),[int]$CameraTestPort=0)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
[void][Reflection.Assembly]::LoadFrom((Join-Path $HostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$fixture=[IO.Path]::GetFullPath($fixture);$code=Join-Path $fixture 'code';$data=Join-Path $fixture 'data';$legacy=Join-Path $fixture 'legacy'
New-Item -ItemType Directory -Path $code,$data,$legacy -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $code 'data_location.py'),'')
$env:AUDIO_MEMORY_ROOT=$data
if([AiAudioMemory.AudioControls]::DataRoot($code) -ne $data){throw 'Data root mismatch'}
if([AiAudioMemory.AudioControls]::CodeRoot($data) -ne $code){throw 'Code root mismatch'}
if([AiAudioMemory.AudioControls]::RootArgument($data) -notlike '*--root*'){throw 'Missing root argument'}
if([AiAudioMemory.AudioControls]::DataRoot($legacy) -ne $legacy){throw 'Legacy root changed'}
if([AiAudioMemory.AudioControls]::RootArgument($legacy) -ne ''){throw 'Legacy arguments changed'}
$dir=Join-Path $data ('out\'+(Get-Date).ToString('yyyyMMdd'));New-Item -ItemType Directory -Path $dir -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $dir 'timeline.jsonl'),('{"t":"10:00","text":"boundary-fixture","file":"fixture","start":0,"end":1}' + "`n"),(New-Object Text.UTF8Encoding($false)))
[void][AiAudioMemory.AudioControls]::DataRoot($ProgramRoot)
$snap=[AiAudioMemory.AudioPane]::ReadSnapshot($data,'transcriber.stdout.log',(Get-Date))
if(-not $snap.Transcript.Contains('boundary-fixture')){throw 'Data snapshot not loaded'}
$range=$snap.Ranges[0]
$note=[AiAudioMemory.Corrections]::Add($data,$range,0,8,'fixture instruction','replacement')
if($note.selected -ne 'boundary'){throw 'Service annotation selection failed'}
$batch=[AiAudioMemory.Corrections]::Submit($data)
[AiAudioMemory.Corrections]::FailBatch($data,$batch,'fixture')
if(([AiAudioMemory.Corrections]::Read($data)).annotations[0].status -ne 'failed'){throw 'Service failure state missing'}
[AiAudioMemory.Corrections]::Remove($data,$note.id)
if(([AiAudioMemory.Corrections]::Read($data)).annotations.Count -ne 0){throw 'Service annotation removal failed'}
[AiAudioMemory.AudioControls]::Classroom($data,$true)
if(-not [AiAudioMemory.AudioControls]::Classroom($data)){throw 'Classroom control failed'}
$subtitle=New-Object 'System.Collections.Generic.Dictionary[string,object]';$subtitle['enabled']=$true
[AiAudioMemory.AudioControls]::SaveSubtitleSettings($data,$subtitle)
if(-not [AiAudioMemory.AudioControls]::SubtitleSettings($data)['enabled']){throw 'Subtitle settings failed'}
[AiAudioMemory.AudioControls]::Switch($data,'local')
if([AiAudioMemory.AudioControls]::Mode($data,$false) -ne 'local'){throw 'Transcription control failed'}
$notes=[AiAudioMemory.AudioControls]::Notes($data);$notes.enabled=$false
[AiAudioMemory.AudioControls]::SaveNotes($data,$notes)
[IO.File]::WriteAllText((Join-Path $code 'recorder.py'),'')
$ui=Join-Path $code 'toolbox-module';New-Item -ItemType Directory -Path $ui -Force | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.xaml' | Copy-Item -Destination $ui
[IO.File]::WriteAllText((Join-Path $data 'classroom-mode.json'),'{"enabled":true}')
$pane=New-Object AiAudioMemory.AudioPane($ui)
[void][AiAudioMemory.AudioControls]::DataRoot($ProgramRoot)
if($CameraTestPort -gt 0){
 $env:AUDIO_MEMORY_TEST_SCENE_PORT=[string]$CameraTestPort
 $scene=Join-Path $data 'out\scene';New-Item -ItemType Directory -Path $scene -Force | Out-Null
 $runtime=@{pid=123;port=$CameraTestPort;token='test-token'} | ConvertTo-Json -Compress
 [IO.File]::WriteAllText((Join-Path $scene 'runtime.json'),$runtime,(New-Object Text.UTF8Encoding($false)))
 $camera=$pane.GetType().GetField('camera',[Reflection.BindingFlags]'Instance,NonPublic').GetValue($pane)
 $call=$camera.GetType().GetMethod('Call',[Reflection.BindingFlags]'Instance,NonPublic')
 $status=$call.Invoke($camera,@('/status',$null))
 if([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('frame')) -ne $status['frameImageBase64']){throw 'Camera service image missing'}
}
$field=$pane.GetType().GetField('current',[Reflection.BindingFlags]'Instance,NonPublic');$field.SetValue($pane,$snap)
$pane.Close()
if(-not [AiAudioMemory.AudioControls]::Classroom($data)){throw 'Closing UI disabled classroom mode'}
if(Test-Path -LiteralPath (Join-Path $code 'out')){throw 'Data written to code root'}
$state=New-Object AiAudioMemory.CorrectionState
$old=New-Object AiAudioMemory.CorrectionRecord
$old.sourceFile='D:\old\out\20261109\timeline.jsonl';$old.file='fixture.wav';$old.start=0;$old.end=1;$old.original='before';$old.text='after';$old.revision=1
$state.records.Add('old-id',$old)
$new=Join-Path $data 'out\20261109\timeline.jsonl'
if([AiAudioMemory.Corrections]::FindRecord($state,$new,'fixture.wav',0,1,'before') -ne 'old-id'){throw 'Relocated correction not found'}
$state.records.Add('other-id',$old);$conflict=$false
try{[AiAudioMemory.Corrections]::FindRecord($state,$new,'fixture.wav',0,1,'before') | Out-Null}catch{$conflict=$true}
if(-not $conflict){throw 'Ambiguous correction accepted'}
Write-Output 'PASS: split code/data roots and legacy binding'
