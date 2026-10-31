$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
function Pump{$f=New-Object Windows.Threading.DispatcherFrame;[void][Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$f.Continue=$false});[Windows.Threading.Dispatcher]::PushFrame($f)}
function Assert($v,$m){if(-not $v){throw $m}}
$pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot);$w=New-Object Windows.Window
try {
 $vocab=$pane.GetType().GetField('vocabulary',[Reflection.BindingFlags]'Instance,NonPublic').GetValue($pane);$v=$vocab.View
 $w.Width=1250;$w.Height=940;$w.Content=$pane.View;$w.Show();$pane.View.FindName('WorkspaceTabs').SelectedIndex=1;$pane.View.FindName('ClassroomVisualTab').Visibility='Visible';$pane.View.FindName('ClassroomTabs').Visibility='Visible';$pane.View.FindName('ClassroomGate').Visibility='Collapsed';$pane.View.FindName('ClassroomTabs').SelectedItem=$pane.View.FindName('ClassroomVisualTab');Pump
 Assert ($v.FindName('Cases').Items.Count -eq 3) 'Three case slots missing'
 Assert ($v.FindName('Cache').IsChecked -eq $false) 'Formal test reused cached results by default'
 $runtime=Split-Path $PSScriptRoot -Parent
 $catalog=Get-Content -LiteralPath (Join-Path $runtime 'visual-models\catalog.json') -Raw|ConvertFrom-Json
 Assert ($v.FindName('Models').Items.Count -eq @($catalog.catalog|Where-Object{$_.task -eq 'ocr'}).Count) 'Active OCR menu does not match catalog'
 foreach($x in $v.FindName('Models').Items){Assert $x.id.StartsWith('local:') 'Cloud OCR leaked into menu'}
 $v.FindName('TaskMode').SelectedIndex=1;Pump
 Assert ($v.FindName('Models').Items.Count -ge 1) 'Vision menu incomplete'
 foreach($x in $v.FindName('Models').Items){Assert (-not $x.id.StartsWith('local:')) 'OCR leaked into vision menu'}
 $v.FindName('Cases').SelectedIndex=0;Pump;Assert ($v.FindName('Run').IsEnabled -eq [AiAudioMemory.AudioControls]::Classroom($runtime)) 'Classroom gate mismatch'
 $v.FindName('Cases').SelectedIndex=2;$v.FindName('TaskMode').SelectedIndex=0;Pump
 Assert ($v.FindName('Run').IsEnabled -eq [AiAudioMemory.AudioControls]::Classroom($runtime)) 'Classroom gate mismatch'
 Assert ($v.FindName('Models').SelectedValue -eq 'local:ppocr-v6-small') 'Wrong initial OCR model'
 $frame=New-Object Windows.Threading.DispatcherFrame;$timer=New-Object Windows.Threading.DispatcherTimer;$timer.Interval=[TimeSpan]::FromMilliseconds(300);$timer.Add_Tick({$timer.Stop();$frame.Continue=$false});$timer.Start();[Windows.Threading.Dispatcher]::PushFrame($frame);$w.UpdateLayout();Pump;Assert ($null -ne $v.FindName('Preview').Source) 'Prepared image preview disappeared';Write-Output ('Preview layout: '+$v.FindName('ImageFit').ActualWidth+' x '+$v.FindName('ImageFit').ActualHeight);$bmp=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]$w.ActualWidth,[int]$w.ActualHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32);$bmp.Render($w);$enc=New-Object Windows.Media.Imaging.PngBitmapEncoder;$enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp));$file=[IO.File]::Create((Join-Path $PSScriptRoot 'design/visual-manual-experiment.png'));try{$enc.Save($file)}finally{$file.Dispose()}
 'PASS: three prepared cases, active OCR catalog, vision excludes dedicated OCR, small default, no auto-run and complex preview; no image inference executed'
}finally{$pane.Close();$w.Close()}
