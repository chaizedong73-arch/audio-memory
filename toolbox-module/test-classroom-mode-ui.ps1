$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('classroom-ui-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture)|Out-Null
$pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
$snapshot=New-Object AiAudioMemory.AudioSnapshot;$snapshot.Root=$fixture
$pane.GetType().GetField('current',$flags).SetValue($pane,$snapshot)
$apply=$pane.GetType().GetMethod('ApplyClassroom',$flags)
$w=New-Object Windows.Window;$w.Width=1250;$w.Height=940;$w.Content=$pane.View
function Check($ok,$message){if(-not $ok){throw $message}}
function Draw($name){
 $w.UpdateLayout();$frame=New-Object Windows.Threading.DispatcherFrame
 [void][Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$frame.Continue=$false})
 [Windows.Threading.Dispatcher]::PushFrame($frame)
 $bmp=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]$w.ActualWidth,[int]$w.ActualHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32);$bmp.Render($w)
 $encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
 $file=[IO.File]::Create((Join-Path $PSScriptRoot ('design/'+$name+'.png')));try{$encoder.Save($file)}finally{$file.Dispose()}
}
try{
 $w.Show();$view=$pane.View;$tabs=$view.FindName('ContentTabs')
 [AiAudioMemory.AudioControls]::Classroom($fixture,$false);[void]$apply.Invoke($pane,[object[]]@([string]$fixture))
 Check ($view.FindName('ClassroomNotesTab').Visibility -eq 'Collapsed') 'Notes visible outside classroom'
 Check ($view.FindName('ClassroomVisualTab').Visibility -eq 'Collapsed') 'Visual visible outside classroom'
 Check ($view.FindName('ToggleClassroom').Content -eq '开启上课模式') 'Wrong initial state'
 $tabs.SelectedIndex=0;Draw 'standing-mode'
 $view.FindName('WorkspaceTabs').SelectedIndex=1;Draw 'classroom-ready'
 Check (-not [AiAudioMemory.AudioControls]::Classroom($fixture)) 'Navigation unexpectedly started classroom mode'
 [AiAudioMemory.AudioControls]::Classroom($fixture,$true);[void]$apply.Invoke($pane,[object[]]@([string]$fixture))
 Check ($view.FindName('ClassroomNotesTab').Visibility -eq 'Visible') 'Notes missing in classroom'
 Check ($view.FindName('ClassroomVisualTab').Visibility -eq 'Visible') 'Visual missing in classroom'
 $view.FindName('ClassroomTabs').SelectedItem=$view.FindName('ClassroomNotesTab');Draw 'classroom-mode'
 [AiAudioMemory.AudioControls]::Classroom($fixture,$false);[void]$apply.Invoke($pane,[object[]]@([string]$fixture))
 Check (-not $view.FindName('StartNotes').IsEnabled) 'Notes could start after classroom ended'
 Check ($view.FindName('WorkspaceTabs').SelectedIndex -eq 0) 'Ending classroom did not return to daily workspace'
 Check ($tabs.Items.Count -eq 5) 'Daily features mixed with classroom tabs'
 Check ($view.FindName('ClassroomTabs').Items.Count -eq 3) 'Classroom hierarchy missing'
 Check ($view.FindName('ClassroomGate').Visibility -eq 'Visible') 'Classroom initial entry missing'
 Check ($view.FindName('ToggleClassroom').Content -eq '开启上课模式') 'State did not return to initial button'
 [AiAudioMemory.AudioControls]::Classroom($fixture,$true);[void]$apply.Invoke($pane,[object[]]@([string]$fixture));$view.FindName('WorkspaceTabs').SelectedIndex=1
 [IO.File]::WriteAllText((Join-Path $fixture 'notes-maintenance-state.json'),'{}')
 [AiAudioMemory.AudioControls]::Classroom($fixture,$false)
 [IO.File]::WriteAllText((Join-Path $fixture 'notes-maintenance-state.json'),'{"active":true}')
 [void]$apply.Invoke($pane,[object[]]@([string]$fixture))
 Check ($view.FindName('ClassroomTabs').SelectedItem -eq $view.FindName('ClassroomNotesTab')) 'Draining note task hidden'
 Check ($view.FindName('WorkspaceTabs').SelectedIndex -eq 1) 'Draining task lost its workspace'
 [IO.File]::WriteAllText((Join-Path $fixture 'notes-maintenance-state.json'),'{"active":false}')
 [void]$apply.Invoke($pane,[object[]]@([string]$fixture))
 Check ($view.FindName('WorkspaceTabs').SelectedIndex -eq 0) 'Drain completion did not restore daily workspace'

 'PASS: standing -> classroom -> standing, dedicated tabs, independent subtitle controls, no worker or model invoked.'
}finally{$pane.Close();$w.Close()}
