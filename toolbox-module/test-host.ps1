$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
$assembly=[Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiTools-audio-native.exe'))
$type=$assembly.GetType('AiAgentMonitor.ToolManager',$true)
$static=[Reflection.BindingFlags]'Static,NonPublic'
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
$type.GetField('Root',$static).SetValue($null,$hostRoot)
$type.GetField('RegistryPath',$static).SetValue($null,(Join-Path $hostRoot 'data\process-registry.json'))
$type.GetField('SignalPath',$static).SetValue($null,(Join-Path $hostRoot 'data\manager-show'))
$manager=[Activator]::CreateInstance($type,$true)
$window=$type.GetField('window',$flags).GetValue($manager)
try{
 [void]$type.GetMethod('OpenModuleById',$flags).Invoke($manager,@('audio-memory'))
 $views=$type.GetField('activeViews',$flags).GetValue($manager)
 if(-not $views.ContainsKey('audio-memory')){throw 'Real host did not load audio module'}
 $pane=$views['audio-memory']; if($pane.GetType().Name -eq 'HostEntry'){$pane=$pane.GetType().GetField('inner',$flags).GetValue($pane)}
 if($null -eq $pane.View.FindName('Transcript') -or $null -eq $pane.View.FindName('LogPicker')){throw 'Native content missing'}
 $tabs=$window.FindName('WorkbenchTabs')
 if($tabs.SelectedItem.Header -ne '录音记忆'){throw 'Host navigation failed'}
 $until=(Get-Date).AddSeconds(15)
 do{
  $frame=New-Object Windows.Threading.DispatcherFrame
  [void]$window.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::Background,[Action]{$frame.Continue=$false})
  [Windows.Threading.Dispatcher]::PushFrame($frame)
  $current=$pane.GetType().GetField('current',$flags).GetValue($pane)
 }while($null -eq $current -and (Get-Date) -lt $until)
 if($null -eq $current){throw 'Real host did not receive runtime snapshot'}
 [pscustomobject]@{result='PASS';hostEntry='录音记忆';native=$true;recording=$current.Recording;model=$current.Model;materialReadable=($current.MaterialPath.Length -gt 0);transcriptCharacters=$current.Transcript.Length}|ConvertTo-Json -Compress
}finally{
 if($pane){$pane.Close()}
 $window.Close()
}
