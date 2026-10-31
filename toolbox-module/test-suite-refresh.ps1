$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$runtime=Split-Path $PSScriptRoot -Parent
$fixture=Join-Path $runtime ('out\visual-vocabulary\experiment\refresh-check-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($fixture)
[IO.File]::WriteAllText((Join-Path $fixture 'classroom-mode.json'),'{"enabled":true}')
$file=Join-Path $fixture 'visual-experiment-suite.json'
$full=[IO.File]::ReadAllText((Join-Path $runtime 'visual-experiment-suite.json'))
$missing=$full|ConvertFrom-Json
foreach($c in $missing.cases){$c.ocrGold='';$c.visionGold=''}
[IO.File]::WriteAllText($file,($missing|ConvertTo-Json -Depth 6))
$pane=New-Object AiAudioMemory.VisualVocabularyPane($PSScriptRoot,[Func[string]]{$fixture})
try{
 $view=$pane.View
 if($view.FindName('Run').IsEnabled){throw 'Missing standards enabled inference'}
 $view.FindName('Cases').SelectedIndex=0
 [IO.File]::WriteAllText($file,$full)
 $pane.RefreshSuite()
 if($view.FindName('Cases').SelectedIndex -ne 0){throw 'Refresh lost selected case'}
 foreach($i in 0,1,2){
  $view.FindName('Cases').SelectedIndex=$i
  if(-not $view.FindName('Run').IsEnabled){throw ('Prepared case remains disabled: '+$i)}
 }
 $view.FindName('Cases').SelectedIndex=0
 $changed=$full|ConvertFrom-Json;$changed.cases[0].ocrGold=''
 [IO.File]::WriteAllText($file,($changed|ConvertTo-Json -Depth 6))
 $pane.RefreshSuite()
 if($view.FindName('Run').IsEnabled){throw 'Removed gold did not disable button'}
 'PASS: missing -> six gold files -> all three cases enabled -> removed gold disables; selected case retained. No inference.'
}finally{
 $pane.Close()
 foreach($p in @($file)){if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p}}
 # Fixture cache folders can remain for diagnosis; no recursive deletion.
}
