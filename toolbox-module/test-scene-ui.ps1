$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$parentPane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
$pane=$parentPane.GetType().GetField('camera',$flags).GetValue($parentPane)
$fixture=Join-Path (Split-Path $PSScriptRoot -Parent) ('out\scene\tests\workspace-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture)|Out-Null
[AiAudioMemory.AudioControls]::Classroom($fixture,$true)
$snapshot=New-Object AiAudioMemory.AudioSnapshot;$snapshot.Root=$fixture
$parentPane.GetType().GetField('current',$flags).SetValue($parentPane,$snapshot)
[void]$parentPane.GetType().GetMethod('ApplyClassroom',$flags).Invoke($parentPane,[object[]]@([string]$fixture))
$parentPane.View.FindName('WorkspaceTabs').SelectedIndex=1
$parentPane.View.FindName('ClassroomTabs').Visibility='Visible'
$parentPane.View.FindName('ClassroomGate').Visibility='Collapsed'
$parentPane.View.FindName('ClassroomTabs').SelectedItem=$parentPane.View.FindName('ClassroomCameraTab')
$window=New-Object Windows.Window;$window.Width=1080;$window.Height=850;$window.Title='现场采集界面验收';$window.Content=$parentPane.View
try{
 $window.Show();$window.UpdateLayout()
 $frame=New-Object Windows.Threading.DispatcherFrame
 [void]$window.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$frame.Continue=$false})
 [Windows.Threading.Dispatcher]::PushFrame($frame)
 $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap(1080,850,96,96,[Windows.Media.PixelFormats]::Pbgra32);$bitmap.Render($window)
 $encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
 $file=[IO.File]::Create((Join-Path $PSScriptRoot 'design/scene-camera-native.png'));try{$encoder.Save($file)}finally{$file.Dispose()}
 $flags=[Reflection.BindingFlags]'Instance,NonPublic'
 if(-not $pane.GetType().GetField('start',$flags).GetValue($pane).IsEnabled){throw 'Start unavailable'}
 if($pane.GetType().GetField('record',$flags).GetValue($pane).IsEnabled){throw 'Record enabled without phone'}
 'PASS: native scene pane rendered, start available, record blocked without phone.'
}finally{$parentPane.Close();$window.Close()}
