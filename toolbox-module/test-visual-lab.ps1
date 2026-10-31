param([switch]$Cloud)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
function Assert($v,$m){if(-not $v){throw $m}}
function Pump{$f=New-Object Windows.Threading.DispatcherFrame;[void][Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$f.Continue=$false});[Windows.Threading.Dispatcher]::PushFrame($f)}
function Click($b){$b.RaiseEvent((New-Object Windows.RoutedEventArgs([Windows.Controls.Button]::ClickEvent)));Pump}
function Wait-Test($view){$until=(Get-Date).AddSeconds(65);while(-not $view.FindName('Run').IsEnabled -and (Get-Date) -lt $until){Pump;Start-Sleep -Milliseconds 40};Pump;Assert $view.FindName('Run').IsEnabled 'Test did not return to ready'}
function Capture($window,$name){$window.UpdateLayout();$dir=Join-Path $PSScriptRoot 'design';[void][IO.Directory]::CreateDirectory($dir);foreach($scale in @(1,2)){$bmp=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]($window.ActualWidth*$scale),[int]($window.ActualHeight*$scale),(96*$scale),(96*$scale),[Windows.Media.PixelFormats]::Pbgra32);$bmp.Render($window);$enc=New-Object Windows.Media.Imaging.PngBitmapEncoder;$enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp));$stream=[IO.File]::Create((Join-Path $dir ($name+'-'+$scale+'x.png')));try{$enc.Save($stream)}finally{$stream.Dispose()}}}

$pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
$window=New-Object Windows.Window
try {
 $vocab=$pane.GetType().GetField('vocabulary',[Reflection.BindingFlags]'Instance,NonPublic').GetValue($pane);$view=$vocab.View
 $window.Width=1200;$window.Height=900;$window.Content=$pane.View;$window.Show();$pane.View.FindName('WorkspaceTabs').SelectedIndex=1;$pane.View.FindName('ClassroomVisualTab').Visibility='Visible';$pane.View.FindName('ClassroomTabs').Visibility='Visible';$pane.View.FindName('ClassroomGate').Visibility='Collapsed';$pane.View.FindName('ClassroomTabs').SelectedItem=$pane.View.FindName('ClassroomVisualTab');Pump
 $vocab.LoadImage((Join-Path (Split-Path $PSScriptRoot -Parent) 'out\visual-vocabulary\runs\lab-outline\input.png'),$false)
 $view.FindName('TaskMode').SelectedIndex=1;$view.FindName('Models').SelectedValue='doubao-seed-2-0-mini-260428';Pump
 Click $view.FindName('Run');Wait-Test $view
 Assert ($view.FindName('Words').Items.Count -gt 0) 'Visual result not shown'
 $view.FindName('FullText').Parent.IsExpanded=$true;Pump
 Capture $window 'visual-lab-outline-vision'
 'PASS: actual diagram vision result displayed'
}finally{$pane.Close();$window.Close()}
