param([Parameter(Mandatory=$true)][string]$HostRoot,[Parameter(Mandatory=$true)][string]$OtherHost,[Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$ArchivePath)
$ErrorActionPreference='Stop'
$HostRoot=[IO.Path]::GetFullPath($HostRoot);$OtherHost=[IO.Path]::GetFullPath($OtherHost);$DataRoot=[IO.Path]::GetFullPath($DataRoot);$ArchivePath=[IO.Path]::GetFullPath($ArchivePath)
Add-Type -AssemblyName System.IO.Compression,System.IO.Compression.FileSystem
[void][Reflection.Assembly]::LoadFrom((Join-Path $HostRoot 'AiWorkbench.Contracts.dll'))
$assembly=[Reflection.Assembly]::LoadFrom((Join-Path $HostRoot 'AiTools-audio-native.exe'))
$type=$assembly.GetType('AiAgentMonitor.ModuleCatalog',$true)
$catalog=[Activator]::CreateInstance($type,@($HostRoot))
$package=@($catalog.Packages | Where-Object {$_.Id -eq 'audio-memory'})[0]
if($null -eq $package -or -not $package.Subscribed){throw 'Subscribed package not found'}
$marker=Join-Path $DataRoot 'preserve-fixture.txt';[IO.File]::WriteAllText($marker,'preserve')
$catalog.Export($package,$ArchivePath)
$catalog.Subscribe('audio-memory',$false)
$package=@($catalog.Packages | Where-Object {$_.Id -eq 'audio-memory'})[0]
if($package.Subscribed -or [IO.File]::ReadAllText($marker) -ne 'preserve'){throw 'Removal changed data'}
$catalog.Subscribe('audio-memory',$true)
$import=[Activator]::CreateInstance($type,@($OtherHost))
if($import.Import($ArchivePath) -ne 'audio-memory'){throw 'Import failed'}
$imported=@($import.Packages | Where-Object {$_.Id -eq 'audio-memory'})[0]
if($null -eq $imported -or -not $imported.Subscribed){throw 'Imported package not subscribed'}
$bad=$ArchivePath+'.invalid.zip';$zip=[IO.Compression.ZipFile]::Open($bad,[IO.Compression.ZipArchiveMode]::Create)
try{[void]$zip.CreateEntry('../escape.txt')}finally{$zip.Dispose()}
$rejected=$false;try{[void]$import.Import($bad)}catch{$rejected=$true}
if(-not $rejected -or [IO.File]::ReadAllText($marker) -ne 'preserve'){throw 'Invalid package accepted or data changed'}
'PASS: subscribe, remove preserving data, export/import, invalid package'
