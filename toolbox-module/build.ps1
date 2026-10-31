param([string]$HostRoot=(Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$ErrorActionPreference='Stop'
if(-not(Test-Path -LiteralPath (Join-Path $HostRoot 'AiWorkbench.Contracts.dll'))){$HostRoot=Join-Path $env:USERPROFILE '.tools\ai-agent-monitor'}
if(-not(Test-Path -LiteralPath (Join-Path $HostRoot 'AiWorkbench.Contracts.dll'))){throw 'Missing AiWorkbench.Contracts.dll. Build the AI Workbench host first and pass its directory with -HostRoot.'}
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Xaml
$compiler=Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
$references=@('System.Web.Extensions.dll','System.Xaml.dll',(Join-Path $HostRoot 'AiWorkbench.Contracts.dll'),[Windows.Window].Assembly.Location,[Windows.Media.Brush].Assembly.Location,[Windows.Threading.Dispatcher].Assembly.Location)
& $compiler /nologo /target:library /codepage:65001 ('/out:'+(Join-Path $PSScriptRoot 'AudioMemory.dll')) @($references|ForEach-Object {'/reference:'+$_}) (Join-Path $PSScriptRoot 'AudioPane.cs') (Join-Path $PSScriptRoot 'Corrections.cs') (Join-Path $PSScriptRoot 'AudioControls.cs') (Join-Path $PSScriptRoot 'VisualVocabulary.cs') (Join-Path $PSScriptRoot 'SceneCamera.cs')
if($LASTEXITCODE -ne 0){throw 'Audio module build failed'}
