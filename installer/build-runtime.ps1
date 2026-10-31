param(
  [Parameter(Mandatory=$true)][string]$BuildPython,
  [Parameter(Mandatory=$true)][string]$ModelDir,
  [Parameter(Mandatory=$true)][string]$InnoCompiler,
  [Parameter(Mandatory=$true)][string]$Stage
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $Stage 'runtime'
if (Test-Path -LiteralPath $runtime) { throw 'Runtime staging directory already exists; choose a fresh stage.' }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
$zip = Join-Path $Stage 'python-3.13.12-embed-amd64.zip'
Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip' -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath $runtime
[IO.File]::WriteAllText((Join-Path $runtime 'python313._pth'), "python313.zip`n.`n..`nLib\site-packages`nimport site`n")
& $BuildPython -m pip install --no-compile --target (Join-Path $runtime 'Lib\site-packages') -r (Join-Path $project 'requirements-core.txt') -r (Join-Path $project 'requirements-vision.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$expected = 'D01C3014881C9C6F3133C182F3D2887EB6CA1C789A7538C5C007196857A0A6A9'
if ((Get-FileHash -LiteralPath (Join-Path $ModelDir 'model.bin') -Algorithm SHA256).Hash -ne $expected) { throw 'Model does not match Systran/faster-whisper-base.' }
foreach ($file in 'config.json','model.bin','tokenizer.json','vocabulary.txt') { if (-not (Test-Path -LiteralPath (Join-Path $ModelDir $file) -PathType Leaf)) { throw "Model file missing: $file" } }
& $InnoCompiler "/DRuntimeDir=$runtime" "/DModelDir=$ModelDir" (Join-Path $PSScriptRoot 'AudioMemory.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
