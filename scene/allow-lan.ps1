param([Parameter(Mandatory=$true)][int]$OwnerPid,[Parameter(Mandatory=$true)][string]$Address)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$runtime=Join-Path $root 'out\scene\runtime.json'
$pairing=Join-Path $root 'out\scene\wifi\pairing.json'
$state=Get-Content -LiteralPath $runtime -Raw -Encoding UTF8|ConvertFrom-Json
$wifi=Get-Content -LiteralPath $pairing -Raw -Encoding UTF8|ConvertFrom-Json
if($state.pid -ne $OwnerPid -or $wifi.ip -ne $Address){throw 'Capture identity changed'}
$ip=[Net.IPAddress]::Parse($Address)
if($ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or [Net.IPAddress]::IsLoopback($ip)){throw 'Invalid LAN address'}
$owner=Get-Process -Id $OwnerPid
$created=$owner.StartTime
$config=Get-Content -LiteralPath (Join-Path $root 'config\integrations.json') -Raw -Encoding UTF8|ConvertFrom-Json
$registry=Join-Path $config.toolboxRoot 'registry.mjs'
$name='Scene-LAN-Firewall-'+$OwnerPid
$rule='AIRecordingCamera-LAN-'+$OwnerPid
$receipt=Join-Path $root 'out\scene\wifi\firewall.json'
$mutex=New-Object Threading.Mutex($false,('Local\AIRecordingCameraFirewall-'+$OwnerPid))
if(-not $mutex.WaitOne(0)){$mutex.Dispose();return}
& node $registry register --owner chatgpt --name $name --pid $PID --desc 'Temporary LAN access; removed when camera receiver exits'
try{
 New-NetFirewallRule -Name $rule -DisplayName 'AI Recording Camera - temporary LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 19644,19645 -LocalAddress $Address -RemoteAddress LocalSubnet -Profile Any|Out-Null
 @{active=$true;pid=$PID;ownerPid=$OwnerPid;address=$Address;ports=@(19644,19645)}|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding UTF8
 while(Test-Path -LiteralPath $runtime){
  $process=Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue
  if(-not $process -or $process.StartTime -ne $created){break}
  $current=Get-Content -LiteralPath $runtime -Raw -Encoding UTF8|ConvertFrom-Json
  if($current.pid -ne $OwnerPid){break}
  Start-Sleep -Seconds 1
 }
}finally{
 Remove-NetFirewallRule -Name $rule -ErrorAction SilentlyContinue
 @{active=$false;ownerPid=$OwnerPid}|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding UTF8
 & node $registry unregister --name $name
 $mutex.ReleaseMutex();$mutex.Dispose()
}
