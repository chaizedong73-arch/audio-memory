param([switch]$Capture)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('audio-pane-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($fixture)
$utf8=New-Object Text.UTF8Encoding($false)
function Write-TestFile($path,$text){[void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path));[IO.File]::WriteAllText($path,$text,$utf8)}
function Assert($value,$message){if(-not $value){throw $message}}
try{
 $now=Get-Date;$day=$now.ToString('yyyyMMdd');$daydir=Join-Path $fixture ('out\'+$day)
 $cloud=Join-Path $fixture ('out\cloud-asr-fixture\'+$day)
 Write-TestFile (Join-Path $fixture 'record\sample.wav') 'fixture'
 $row=@{t='16:55:00';text='课堂内容按时间汇集，保留转写出处，方便对照课程笔记。';file='fixture';start=60900;end=60915;ts=([DateTimeOffset]$now.AddSeconds(-20)).ToUnixTimeMilliseconds()/1000.0}|ConvertTo-Json -Compress
 Write-TestFile (Join-Path $daydir 'timeline.jsonl') ($row+"`n")
 Write-TestFile (Join-Path $cloud 'timeline.jsonl') ($row+"`n")
 Write-TestFile (Join-Path $daydir 'memory.md') "# 今日记忆`n`n- 待核对：课程中的关键定义与适用条件。"
 Write-TestFile (Join-Path $fixture 'cloud-asr.stdout.log') '{"seconds":15,"latency":2.18,"estimatedYuan":0.083}'
 $state=@{active=$true;deadline=[DateTimeOffset]::Now.AddHours(2).ToUnixTimeSeconds();model='doubao-seed-2-0-mini-260428';latestDayDir=$cloud;latestLatencySeconds=2.18;estimatedYuan=0.083;budgetYuan=5;completed=@('a','b')}
 Write-TestFile (Join-Path $fixture 'cloud-asr-trial.json') ($state|ConvertTo-Json)
 $snapshot=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now)
 Assert ($snapshot.RecordingHealthy -and $snapshot.Model -eq '豆包 2.0 Mini') 'Fresh recording/cloud detection failed'
 Assert ($snapshot.Transcript.Contains('课堂内容') -and $snapshot.Memory.Contains('关键定义')) 'Native material read failed'
 Assert ($snapshot.Diagnostic -notmatch '课堂内容') 'Diagnostic leaked transcript'
 $range=$snapshot.Ranges[0]
 $note=[AiAudioMemory.Corrections]::Add($fixture,$range,0,4,'这里应为课程内容','课程内容')
 Assert ([AiAudioMemory.Corrections]::Read($fixture).annotations.Count -eq 1) 'Annotation was not persisted'
 $batch=[AiAudioMemory.Corrections]::Submit($fixture)
 $blocked=$false;try{[AiAudioMemory.Corrections]::Submit($fixture)|Out-Null}catch{$blocked=$true}
 Assert $blocked 'Duplicate batch was submitted'
 $runtime=Split-Path $PSScriptRoot -Parent
 $python=Join-Path $runtime '.venv\Scripts\python.exe'
 $code="import sys;sys.path.insert(0,r'$runtime');from annotation_worker import run;run('$batch',r'$fixture',publisher=lambda p:None)"
 & $python -c $code
 if($LASTEXITCODE -ne 0){throw 'Native-to-worker correction failed'}
 $snapshot=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now)
 Assert ($snapshot.Transcript.Contains('课程内容') -and -not $snapshot.Transcript.Contains('课堂内容')) 'Corrected body did not refresh'
 $pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
 $flags=[Reflection.BindingFlags]'Instance,NonPublic'
 $apply=$pane.GetType().GetMethod('Apply',$flags)
 [void]$apply.Invoke($pane,@($snapshot))
 $text=$pane.View.FindName('Transcript');$text.Select(0,5)
 $original=$text.Text
 [void]$apply.Invoke($pane,@($snapshot))
 Assert ($text.Text -eq $original -and $text.SelectionLength -eq 5) 'Unchanged refresh disturbed selection'
 $snapshot.Transcript+="`n继续：新的内容在这里出现。"
 [void]$apply.Invoke($pane,@($snapshot))
 Assert ($text.SelectionLength -eq 5) 'Incremental update lost selection'
 $snapshot.Transcript='较新的开头'+$snapshot.Transcript
 $chosen=$text.SelectedText
 [void]$apply.Invoke($pane,@($snapshot))
 Assert ($text.SelectedText -eq $chosen) 'Shifted material changed the selected text'
 # Large wrapped logs can shrink or reflow before WPF recomputes visible lines.
 $snapshot.Transcript=('换行边界测试文本'*80+"`n")*50
 [void]$apply.Invoke($pane,@($snapshot))
 $text.ScrollToEnd();$snapshot.Transcript="短文本`n新的结果"
 [void]$apply.Invoke($pane,@($snapshot))
 $snapshot.Transcript=$original+"`n16:55:15   对照课程笔记时，将课堂原话与自己的理解分开，保留待核实的问题。"
 [void]$apply.Invoke($pane,@($snapshot))
 if($Capture){
  $design=Join-Path $PSScriptRoot 'design';[void][IO.Directory]::CreateDirectory($design)
  [Windows.Documents.TextElement]::SetFontFamily($pane.View,(New-Object Windows.Media.FontFamily('Segoe UI, Microsoft YaHei')))
  $surface=New-Object Windows.Controls.Border;$surface.Background='#F5F5F7';$surface.Child=$pane.View
  $surface.Measure((New-Object Windows.Size(960,640)))
  $surface.Arrange((New-Object Windows.Rect(0,0,960,640)));$surface.UpdateLayout()
  foreach($scale in @(1,2)){
   $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap((960*$scale),(640*$scale),(96*$scale),(96*$scale),[Windows.Media.PixelFormats]::Pbgra32)
   $bitmap.Render($surface);$encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder
   $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
   $stream=[IO.File]::Create((Join-Path $design ('native-audio-'+$scale+'x.png')))
   try{$encoder.Save($stream)}finally{$stream.Dispose()}
  }
 }
 [IO.File]::SetLastWriteTime((Join-Path $cloud 'timeline.jsonl'),$now.AddMinutes(-3))
 $fallback=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now)
 Assert ($fallback.Model -eq '本地 Whisper' -and $fallback.Health.Contains('本地转写')) 'Stale cloud did not fall back'
 [IO.File]::SetLastWriteTime((Join-Path $fixture 'record\sample.wav'),$now.AddMinutes(-5))
 Assert (-not [AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now).RecordingHealthy) 'Stale recording misreported'
 $state.deadline=[DateTimeOffset]::Now.AddMinutes(-1).ToUnixTimeSeconds()
 Write-TestFile (Join-Path $fixture 'cloud-asr-trial.json') ($state|ConvertTo-Json)
 Assert ([AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now).Health.Contains('到期')) 'Expired trial misreported'
 $blocked=$false;try{[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'ark_config.json',$now)|Out-Null}catch{$blocked=$true}
 Assert $blocked 'Unapproved log read allowed'
 [AiAudioMemory.AudioControls]::Switch($fixture,'local')
 Assert ([AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',$now).Mode -eq 'local') 'Local selection did not persist'
 [AiAudioMemory.AudioControls]::Switch($fixture,'cloud')
 Assert ([AiAudioMemory.AudioControls]::Mode($fixture,$false) -eq 'cloud') 'Cloud selection did not persist'
 [AiAudioMemory.AudioControls]::Switch($fixture,'local')
 $missing=[AiAudioMemory.AudioPane]::ReadSnapshot('','cloud-asr.stdout.log',$now)
 Assert ($missing.Recording -eq '未连接') 'Unbound runtime not handled'
 # Exercise real asynchronous Open/Close against the existing read-only local binding.
 $pane.Open();$until=(Get-Date).AddSeconds(15)
 $background=$pane.GetType().GetField('worker',$flags).GetValue($pane)
 do{
  $frame=New-Object Windows.Threading.DispatcherFrame
  [void]$pane.View.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::Background,[Action]{$frame.Continue=$false})
  [Windows.Threading.Dispatcher]::PushFrame($frame)
 }while(($background.IsBusy -or $null -eq $pane.GetType().GetField('current',$flags).GetValue($pane)) -and (Get-Date) -lt $until)
 Assert (-not $background.IsBusy) 'Async native refresh stalled'
 Assert ($null -ne $pane.GetType().GetField('current',$flags).GetValue($pane)) 'Async snapshot was not applied'
 $pane.Close()
 $timer=$pane.GetType().GetField('timer',$flags).GetValue($pane)
 Assert (-not $timer.IsEnabled) 'Close left UI refresh running'
 'PASS: native snapshots, cloud fallback, expiry, recording health, read boundaries, selection, async lifecycle'
}finally{
 if($pane){$pane.Close()}
 # Only this test-owned temporary directory is removed.
 $resolved=[IO.Path]::GetFullPath($fixture)
 if($resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('audio-pane-')){[IO.Directory]::Delete($resolved,$true)}
}
