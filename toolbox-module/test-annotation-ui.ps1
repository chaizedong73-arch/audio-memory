param([switch]$Capture)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('audio-annotation-'+[Guid]::NewGuid().ToString('N'))
$utf8=New-Object Text.UTF8Encoding($false)
function Assert($value,$message){if(-not $value){throw $message}}
function Pump{
 $frame=New-Object Windows.Threading.DispatcherFrame
 [void][Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$frame.Continue=$false})
 [Windows.Threading.Dispatcher]::PushFrame($frame)
}
function Click($button){$button.RaiseEvent((New-Object Windows.RoutedEventArgs([Windows.Controls.Button]::ClickEvent)))}
try{
 $daydir=Join-Path $fixture ('out\'+(Get-Date -Format yyyyMMdd))
 [void][IO.Directory]::CreateDirectory($daydir)
 $row=@{t='19:07:43';text='这一段讲的是数据库排序：用 order by 按照指定字段排列，最后检查结果。';file='fixture';start=68863;end=68878}|ConvertTo-Json -Compress
 [IO.File]::WriteAllText((Join-Path $daydir 'timeline.jsonl'),$row+"`n",$utf8)
 $snapshot=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',[DateTime]::Now)
 $pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
 $flags=[Reflection.BindingFlags]'Instance,NonPublic'
 $type=$pane.GetType();$type.GetField('current',$flags).SetValue($pane,$snapshot)
 [void]$type.GetMethod('Apply',$flags).Invoke($pane,@($snapshot))
 $window=New-Object Windows.Window
 $window.Title='批注交互验证';$window.Width=[Math]::Min(1080,[Windows.SystemParameters]::WorkArea.Width-32);$window.Height=[Math]::Min(820,[Windows.SystemParameters]::WorkArea.Height-32);$window.Left=16;$window.Top=16;$window.ShowActivated=$false;$window.WindowStyle='None';$window.ResizeMode='NoResize'
 $window.Content=$pane.View;$window.Show();Pump
 $box=$pane.View.FindName('Transcript');[void]$box.Focus();$start=$box.Text.IndexOf('数据库排序');$box.Select($start,5)
 [void]$type.GetMethod('ShowSelectionAction',$flags).Invoke($pane,@());Pump
 $chip=$type.GetField('selectionPopup',$flags).GetValue($pane)
 Assert ($chip.IsOpen -and -not $chip.Child.Child.Focusable) 'Selection action must not take keyboard focus'
 Assert ($box.SelectedText -eq '数据库排序' -and $box.IsInactiveSelectionHighlightEnabled) 'Selection highlight was lost'
 $incoming=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',[DateTime]::Now)
 $incoming.Transcript='新的内容不应顶掉正在批注的选区'
 [void]$type.GetMethod('Apply',$flags).Invoke($pane,@($incoming))
 Assert ($chip.IsOpen -and $box.SelectedText -eq '数据库排序') 'Background refresh dismissed the annotation action'
 Click $chip.Child.Child;Pump
 $popup=$type.GetField('annotationPopup',$flags).GetValue($pane)
 Assert ($popup.IsOpen -and $popup -is [Windows.Controls.Primitives.Popup]) 'Inline annotation popup did not open'
 $panel=$popup.Child.Child
 $instruction=$panel.FindName('InstructionEditor')
 Assert ($null -eq $panel.FindName('ReplacementEditor')) 'Annotation should have only one input field'
 Assert ($instruction -is [Windows.Controls.TextBox] -and -not $instruction.IsReadOnly) 'Instruction editor is not editable'
 Assert ($box.SelectedText -eq '数据库排序') 'Popup cleared the original selection'
 $selectedRect=$box.GetRectFromCharacterIndex($box.SelectionStart)
 $selectedTop=$box.PointToScreen($selectedRect.TopLeft);$selectedBottom=$box.PointToScreen($box.GetRectFromCharacterIndex($box.SelectionStart+$box.SelectionLength-1,$true).BottomRight)
 $popupTop=$popup.Child.PointToScreen((New-Object Windows.Point(0,0)))
 $popupBottom=$popup.Child.PointToScreen((New-Object Windows.Point($popup.Child.ActualWidth,$popup.Child.ActualHeight)))
 Assert ($popupTop.Y -ge $selectedBottom.Y -or $popupBottom.Y -le $selectedTop.Y -or $popupTop.X -ge $selectedBottom.X -or $popupBottom.X -le $selectedTop.X) ("Popup overlaps selected text: popup="+$popupTop+'..'+$popupBottom+' selection='+$selectedTop+'..'+$selectedBottom+' size='+$popup.Child.ActualHeight)
 Click $panel.FindName('SaveAnnotation');Pump
 Assert ($popup.IsOpen -and $panel.FindName('AnnotationError').Text.Length -gt 0) 'Empty save did not preserve editable popup'
 $instruction.Text='请根据上下文改成 SQL 排序的准确表述。'
 # Simulate a save failure: the editor and typed values must stay in place.
 $lock=[IO.File]::Open((Join-Path $fixture '.transcript-corrections.lock'),'OpenOrCreate','ReadWrite','None')
 try{Click $panel.FindName('SaveAnnotation')}finally{$lock.Dispose()}
 Assert ($popup.IsOpen -and $instruction.Text.Contains('SQL') -and $panel.FindName('AnnotationError').Text.Length -gt 0) 'Failed save lost the draft'
 $panel.FindName('AnnotationError').Text=''
 $panel.FindName('AnnotationError').Visibility='Collapsed'
 if($Capture){
  $design=Join-Path $PSScriptRoot 'design';[void][IO.Directory]::CreateDirectory($design)
  $window.UpdateLayout();$popup.Child.UpdateLayout();Pump
  foreach($scale in @(1,2)){
   $visual=New-Object Windows.Media.DrawingVisual;$context=$visual.RenderOpen()
   $context.DrawRectangle((New-Object Windows.Media.VisualBrush($window)),$null,(New-Object Windows.Rect(0,0,$window.ActualWidth,$window.ActualHeight)))
   $origin=$window.PointToScreen((New-Object Windows.Point(0,0)));$location=$popup.Child.PointToScreen((New-Object Windows.Point(0,0)))
   $fromDevice=[Windows.PresentationSource]::FromVisual($window).CompositionTarget.TransformFromDevice
   $delta=$fromDevice.Transform((New-Object Windows.Vector(($location.X-$origin.X),($location.Y-$origin.Y))))
   $context.DrawRectangle((New-Object Windows.Media.VisualBrush($popup.Child)),$null,(New-Object Windows.Rect($delta.X,$delta.Y,$popup.Child.ActualWidth,$popup.Child.ActualHeight)))
   $context.Close()
   $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]($window.ActualWidth*$scale),[int]($window.ActualHeight*$scale),(96*$scale),(96*$scale),[Windows.Media.PixelFormats]::Pbgra32)
   $bitmap.Render($visual);$encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
   $stream=[IO.File]::Create((Join-Path $design ('annotation-popup-'+$scale+'x.png')));try{$encoder.Save($stream)}finally{$stream.Dispose()}
  }
 }
 Click $panel.FindName('SaveAnnotation');Pump
 Assert (-not $popup.IsOpen) 'Successful save left popup open'
 $saved=[AiAudioMemory.Corrections]::Read($fixture)
 Assert ($saved.annotations.Count -eq 1 -and $saved.annotations[0].instruction.Contains('SQL') -and $saved.annotations[0].replacement -eq '') 'Saved annotation did not survive reread'
 [void]$type.GetMethod('Annotate',$flags).Invoke($pane,@($saved.annotations[0]));Pump
 $popup=$type.GetField('annotationPopup',$flags).GetValue($pane);$panel=$popup.Child.Child
 Assert ($panel.FindName('InstructionEditor').Text.Contains('SQL')) 'Editing existing annotation lost text'
 Click $panel.FindName('CancelAnnotation');Pump
 Assert (-not $type.GetField('editing',$flags).GetValue($pane)) 'Cancelled popup left transcript refresh paused'
 Assert ([AiAudioMemory.Corrections]::Read($fixture).annotations.Count -eq 1) 'Cancel created a duplicate annotation'
 # A long paragraph near the viewport edge must place its popup above the selection.
 $rowObject=$row|ConvertFrom-Json;$rowObject.text=('课堂示例内容用于检查多行选区及浮窗边界。'*100)+'测试选区'
 [IO.File]::WriteAllText((Join-Path $daydir 'timeline.jsonl'),($rowObject|ConvertTo-Json -Compress)+"`n",$utf8)
 $edge=[AiAudioMemory.AudioPane]::ReadSnapshot($fixture,'cloud-asr.stdout.log',[DateTime]::Now)
 $type.GetField('current',$flags).SetValue($pane,$edge);[void]$type.GetMethod('Apply',$flags).Invoke($pane,@($edge))
 $box.Select($box.Text.IndexOf('测试选区'),4);$box.ScrollToEnd();Pump
 Click $pane.View.FindName('Annotate');Pump
 $popup=$type.GetField('annotationPopup',$flags).GetValue($pane)
 Assert $popup.IsOpen 'Bottom-edge popup failed to open'
 $rect=$box.GetRectFromCharacterIndex($box.SelectionStart);$top=$box.PointToScreen($rect.TopLeft);$bottom=$box.PointToScreen($box.GetRectFromCharacterIndex($box.SelectionStart+$box.SelectionLength-1,$true).BottomRight)
 $pTop=$popup.Child.PointToScreen((New-Object Windows.Point(0,0)));$pBottom=$popup.Child.PointToScreen((New-Object Windows.Point($popup.Child.ActualWidth,$popup.Child.ActualHeight)))
 Assert ($pTop.Y -ge $bottom.Y -or $pBottom.Y -le $top.Y -or $pTop.X -ge $bottom.X -or $pBottom.X -le $top.X) 'Bottom-edge popup obscures selection'
 Click $popup.Child.Child.FindName('CancelAnnotation');Pump
 # The classroom settings form is exercised without starting a real delegate.
 $model=New-Object AiAudioMemory.NoteModel;$model.id='fixture-model';$model.label='Fixture model'
 $choices=New-Object 'Collections.Generic.List[AiAudioMemory.NoteModel]';$choices.Add($model)
 $note=New-Object AiAudioMemory.NoteSession;$note.id='11111111-1111-4111-8111-111111111111';$note.name='Fixture session';$note.models=$choices
 $list=New-Object 'Collections.Generic.List[AiAudioMemory.NoteSession]';$list.Add($note)
 $picker=$pane.View.FindName('NotesSession');$picker.ItemsSource=$list;$picker.SelectedItem=$note

 $until=(Get-Date).AddSeconds(12)
 while($type.GetField('catalogWorker',$flags).GetValue($pane).IsBusy -and (Get-Date) -lt $until){Pump}
 Pump
 $sessions=$pane.View.FindName('NotesSession');Assert ($sessions.Items.Count -gt 0 -and $sessions.SelectedValue) 'Existing-session selector binding did not resolve the fixture ID'
 Assert ($pane.View.FindName('NotesModel').Items.Count -gt 0) 'Model selector was not populated'
 $notes=Join-Path $fixture 'course-notes';[void][IO.Directory]::CreateDirectory($notes)
 $pane.View.FindName('NotesRoot').Text=$notes
 $pane.View.FindName('NotesDescription').Text='Synthetic classroom settings regression fixture'
 Click $pane.View.FindName('SaveNotesSettings');Pump
 $settings=[AiAudioMemory.AudioControls]::Notes($fixture)
 Assert (-not $settings.enabled -and $settings.notesRoot -eq $notes -and $settings.strategy -eq 'auto') 'Notes setup did not persist safely'
 $pane.View.FindName('ContentTabs').SelectedIndex=3;Pump
 $pending=@{items=@{one=@{id='fixture-symbol';status='needs_confirmation';term='ht-1';question='课件候选是 ht-1，是否使用？';reason='近期出现 ht.1、hz.1、ht-1、he.1，暂不自动定案。'}}}
 [IO.File]::WriteAllText((Join-Path $fixture 'subtitle-confirmations.json'),($pending|ConvertTo-Json -Depth 6),$utf8)
 [void]$type.GetMethod('Apply',$flags).Invoke($pane,@($edge));Pump
 Assert ($pane.View.FindName('SubtitleConfirmation').Visibility -eq 'Visible') 'Symbol confirmation was hidden'
 $pane.View.FindName('SubtitleTerm').Text='ht.1'
 [void]$type.GetMethod('Apply',$flags).Invoke($pane,@($edge));Pump
 Assert ($pane.View.FindName('SubtitleTerm').Text -eq 'ht.1') 'Refresh overwrote edited candidate'
 $pane.View.FindName('SubtitleTerm').Text='ht-1'
 if($Capture){
  $window.UpdateLayout()
  foreach($scale in @(1,2)){
   $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]($window.ActualWidth*$scale),[int]($window.ActualHeight*$scale),(96*$scale),(96*$scale),[Windows.Media.PixelFormats]::Pbgra32)
   $bitmap.Render($window);$encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
   $stream=[IO.File]::Create((Join-Path $design ('classroom-settings-'+$scale+'x.png')));try{$encoder.Save($stream)}finally{$stream.Dispose()}
  }
  $pane.View.FindName('NotesSettingsScroll').ScrollToEnd();Pump;$window.UpdateLayout()
  $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]$window.ActualWidth,[int]$window.ActualHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32)
  $bitmap.Render($window);$encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
  $stream=[IO.File]::Create((Join-Path $design 'classroom-controls-1x.png'));try{$encoder.Save($stream)}finally{$stream.Dispose()}
 }
 'PASS: actual popup entry, persistent selection, editable fields, validation, failed save retention, save/reread, edit/cancel'
}finally{
 if($pane){$pane.Close()};if($window){$window.Close()}
 $resolved=[IO.Path]::GetFullPath($fixture)
 if($resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('audio-annotation-')){if([IO.Directory]::Exists($resolved)){[IO.Directory]::Delete($resolved,$true)}}
}
