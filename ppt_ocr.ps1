param([string]$InputFile,[string]$OutputFile)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
function Await($operation,[Type]$type){$task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation));$task.GetAwaiter().GetResult()}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if(-not $engine){throw 'No installed OCR language'}
$items=@()
foreach($file in (Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json)){
 $stream=$null;$bitmap=$null
 try{
  $storage=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync([string]$file)) ([Windows.Storage.StorageFile])
  $stream=Await ($storage.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $words=@();foreach($line in $result.Lines){foreach($word in $line.Words){$box=$word.BoundingRect;$words+=@{text=$word.Text;x=$box.X;y=$box.Y;width=$box.Width;height=$box.Height}}}
  $items+=@{path=[string]$file;text=$result.Text;words=$words;language=$engine.RecognizerLanguage.LanguageTag;engine='Windows.Media.Ocr'}
 }catch{$items+=@{path=[string]$file;error=$_.Exception.Message}}
 finally{if($bitmap){$bitmap.Dispose()};if($stream){$stream.Dispose()}}
}
[IO.File]::WriteAllText($OutputFile,(ConvertTo-Json -InputObject @($items) -Depth 8),(New-Object Text.UTF8Encoding($false)))
