$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$hostRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
[void][Reflection.Assembly]::LoadFrom((Join-Path $hostRoot 'AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$pane=New-Object AiAudioMemory.AudioPane($PSScriptRoot)
try{$v=$pane.GetType().GetField('vocabulary',[Reflection.BindingFlags]'Instance,NonPublic').GetValue($pane).View
$count=$v.FindName('Words').Items.Count
if($count -le 0){throw 'Last saved user result did not restore'}
@{restored=$true;words=$count;source=$v.FindName('ImageName').Text}|ConvertTo-Json -Compress
}finally{$pane.Close()}
