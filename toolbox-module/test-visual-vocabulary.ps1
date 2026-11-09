param([switch]$Cloud)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
function Assert($v,$m){if(-not $v){throw $m}}
function Pump{$f=New-Object Windows.Threading.DispatcherFrame;[void][Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$f.Continue=$false});[Windows.Threading.Dispatcher]::PushFrame($f)}
function Click($b){$b.RaiseEvent((New-Object Windows.RoutedEventArgs([Windows.Controls.Button]::ClickEvent)));Pump}
function Wait-Test($view){$worker=$vocab.GetType().GetField('worker',[Reflection.BindingFlags]'Instance,NonPublic').GetValue($vocab);$until=(Get-Date).AddSeconds(65);while(($worker.IsBusy -or -not $view.FindName('Run').IsEnabled) -and (Get-Date) -lt $until){Pump;Start-Sleep -Milliseconds 40};Pump;Assert (-not $worker.IsBusy -and $view.FindName('Run').IsEnabled) 'Test did not return to ready'}
function Capture($window,$name){$window.UpdateLayout();$dir=Join-Path $PSScriptRoot 'design';[void][IO.Directory]::CreateDirectory($dir);foreach($scale in @(1,2)){$bmp=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]($window.ActualWidth*$scale),[int]($window.ActualHeight*$scale),(96*$scale),(96*$scale),[Windows.Media.PixelFormats]::Pbgra32);$bmp.Render($window);$enc=New-Object Windows.Media.Imaging.PngBitmapEncoder;$enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp));$stream=[IO.File]::Create((Join-Path $dir ($name+'-'+$scale+'x.png')));try{$enc.Save($stream)}finally{$stream.Dispose()}}}
$pane=$null;$window=$null
try{
 $runtime=Split-Path $PSScriptRoot -Parent
 $pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
 $flags=[Reflection.BindingFlags]'Instance,NonPublic'
 $vocab=$pane.GetType().GetField('vocabulary',$flags).GetValue($pane);$view=$vocab.View
 $window=New-Object Windows.Window;$window.Title='视觉词表 · 验证';$window.Width=1120;$window.Height=850;$window.Content=$pane.View;$window.Show();$pane.View.FindName('WorkspaceTabs').SelectedIndex=1;$pane.View.FindName('ClassroomVisualTab').Visibility='Visible';$pane.View.FindName('ClassroomTabs').Visibility='Visible';$pane.View.FindName('ClassroomGate').Visibility='Collapsed';$pane.View.FindName('ClassroomTabs').SelectedItem=$pane.View.FindName('ClassroomVisualTab');Pump
 $vocab.LoadImage((Join-Path $runtime 'out\ppt-concepts\fixture.png'),$false);Pump
 $models=$view.FindName('Models');Assert ($models.Items.Count -ge 1) 'Local OCR model missing'
 Click $view.FindName('Run');Wait-Test $view
 Assert ($view.FindName('Words').Items.Count -gt 0) ('Local OCR failed: '+$view.FindName('Status').Text)
 $view.FindName('Words').SelectedIndex=0;Pump;Assert ($view.FindName('Markers').Children.Count -eq 1) 'Word did not locate image region'
 Capture $window 'visual-vocabulary-local'
 $window.Height=620;$window.Width=1000;Pump;$window.UpdateLayout()
 $scroll=$view -as [Windows.Controls.ScrollViewer]
 Assert ($null -ne $scroll -and $scroll.ScrollableHeight -gt 0) 'Short viewport has no outer scroll'
 $scroll.ScrollToEnd();Pump
 Assert ($scroll.VerticalOffset -gt 0 -and $view.FindName('Words').ActualHeight -ge 200) 'Result table collapsed or scrolling failed'
 Capture $window 'visual-vocabulary-short'
 $previous=$scroll.VerticalOffset
 $wheel=New-Object Windows.Input.MouseWheelEventArgs([Windows.Input.Mouse]::PrimaryDevice,0,120)
 $wheel.RoutedEvent=[Windows.Input.Mouse]::PreviewMouseWheelEvent;$scroll.RaiseEvent($wheel);Pump
 Assert ($scroll.VerticalOffset -lt $previous) 'Mouse wheel did not scroll outer page'
 $view.LayoutTransform=New-Object Windows.Media.ScaleTransform(1.5,1.5);Pump;$window.UpdateLayout();$scroll.ScrollToEnd();Pump
 Assert ($scroll.ScrollableHeight -gt 0 -and $view.FindName('Words').ActualHeight -ge 200) 'Scaled viewport collapsed result table'
 Capture $window 'visual-vocabulary-scaled'
 $view.LayoutTransform=[Windows.Media.Transform]::Identity;$window.Height=850;$window.Width=1120;Pump;$scroll.ScrollToTop();Pump

 if($Cloud){
  $view.FindName('TaskMode').SelectedIndex=1;Pump
  $models.SelectedValue='doubao-seed-2-0-mini-260428';Pump;Click $view.FindName('Run');Wait-Test $view
  Assert (([string]$view.FindName('ResultMeta').ToolTip).Contains('doubao-seed-2-0-mini')) ('Cloud result missing: '+$view.FindName('Status').Text)
  Capture $window 'visual-vocabulary-mini'
 }
 $view.FindName('TaskMode').SelectedIndex=0;Pump;$models.SelectedValue='local:windows';Pump;Assert (([string]$view.FindName('ResultMeta').ToolTip).Contains('local:windows')) 'Switch did not reuse local result'
 Click $view.FindName('Run');Click $view.FindName('Cancel');Wait-Test $view;Assert ($view.FindName('Status').Text.Contains('已取消')) 'Cancellation did not settle'
 Click $view.FindName('Run');Wait-Test $view;Assert ($view.FindName('Words').Items.Count -gt 0) 'Cannot run again after cancellation'
 $bad=New-Object AiAudioMemory.VocabularyModel;$bad.id='local:bad model';$bad.label='invalid';$models.ItemsSource.Add($bad);$models.Items.Refresh();$models.SelectedItem=$bad;Pump
 Click $view.FindName('Run');Wait-Test $view;Assert ($view.FindName('Status').Text.Contains('未完成')) 'Invalid model was treated as success';Assert ($view.FindName('Words').Items.Count -gt 0) 'Failure destroyed previous result'
 $models.SelectedValue='local:windows';Pump
 'PASS: native photo input, local OCR, model switching, region overlay, cancellation/restart, bounded failure; cloud='+$Cloud
}finally{if($pane){$pane.Close()};if($window){$window.Close()}}
