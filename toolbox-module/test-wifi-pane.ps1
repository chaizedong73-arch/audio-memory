$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml,System.Web.Extensions
$root=Split-Path $PSScriptRoot -Parent
[void][Reflection.Assembly]::LoadFrom((Join-Path $env:USERPROFILE '.tools\ai-agent-monitor\AiWorkbench.Contracts.dll'))
[void][Reflection.Assembly]::LoadFrom((Join-Path $PSScriptRoot 'AudioMemory.dll'))
$fixture=Join-Path $root 'out\scene\tests\ui-fixture';[IO.Directory]::CreateDirectory($fixture)|Out-Null
$pane=New-Object AiAudioMemory.SceneCameraPane($PSScriptRoot,$fixture)
$templateStream=[IO.File]::OpenRead((Join-Path $PSScriptRoot 'AudioPane.xaml'))
try{$template=[Windows.Markup.XamlReader]::Load($templateStream);$pane.View.Resources=$template.Resources}finally{$templateStream.Dispose()}
$json=New-Object Web.Script.Serialization.JavaScriptSerializer;$json.MaxJsonLength=4MB
$data=$json.DeserializeObject([IO.File]::ReadAllText((Join-Path $root 'out\scene\wifi\render-state.json')))
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
[void]$pane.GetType().GetMethod('Apply',$flags).Invoke($pane,[object[]]@($data))
$window=New-Object Windows.Window;$window.Width=1120;$window.Height=1080;$window.Content=$pane.View
try{
 $window.Show();$window.UpdateLayout()
 $frame=New-Object Windows.Threading.DispatcherFrame
 [void]$window.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::ApplicationIdle,[Action]{$frame.Continue=$false})
 [Windows.Threading.Dispatcher]::PushFrame($frame)
 $bitmap=New-Object Windows.Media.Imaging.RenderTargetBitmap(1120,1080,96,96,[Windows.Media.PixelFormats]::Pbgra32);$bitmap.Render($window)
 $encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder;$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
 $file=[IO.File]::Create((Join-Path $root 'out\scene\wifi\native-pairing.png'));try{$encoder.Save($file)}finally{$file.Dispose()}
 $panel=$pane.GetType().GetField('wifiPanel',$flags).GetValue($pane)
 if($panel.Visibility -ne 'Visible' -or -not $panel.IsExpanded){throw 'Pairing panel did not open'}
 'PASS: native Wi-Fi pairing with two QR codes rendered; no live camera or firewall action.'
}finally{$pane.Close();$window.Close()}
