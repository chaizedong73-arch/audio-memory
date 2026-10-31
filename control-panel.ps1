param([string]$Preview = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$root = $PSScriptRoot
$python = Join-Path $root 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $root '.venv\Scripts\python.exe' }
$script:closing = $false
$script:allowClose = $false
$script:components = @{}
$token = [guid]::NewGuid().ToString('N')
$stopRoot = Join-Path ([IO.Path]::GetTempPath()) ('audio-memory-ui-' + $token)
[void][IO.Directory]::CreateDirectory($stopRoot)
$form = New-Object Windows.Forms.Form
$form.Text = 'AI 录音记忆'; $form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object Drawing.Size(690, 505)
$form.MinimumSize = New-Object Drawing.Size(706, 544)
$form.BackColor = [Drawing.Color]::FromArgb(247, 248, 249)
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
function Label([string]$text,[int]$x,[int]$y,[int]$w,[int]$h,[int]$size,[bool]$bold=$false){
 $v=New-Object Windows.Forms.Label; $v.Text=$text; $v.SetBounds($x,$y,$w,$h)
 $style=if($bold){[Drawing.FontStyle]::Bold}else{[Drawing.FontStyle]::Regular}
 $v.Font=New-Object Drawing.Font('Microsoft YaHei UI',$size,$style); $v.ForeColor=[Drawing.Color]::FromArgb(35,43,50); $form.Controls.Add($v); return $v
}
function Button([string]$text,[int]$x,[int]$y,[int]$w){
 $v=New-Object Windows.Forms.Button; $v.Text=$text; $v.SetBounds($x,$y,$w,37)
 $v.FlatStyle='Flat'; $v.BackColor=[Drawing.Color]::White; $v.FlatAppearance.BorderColor=[Drawing.Color]::FromArgb(204,211,218)
 $form.Controls.Add($v); return $v
}
[void](Label '录音记忆' 30 24 300 42 22 $true)
[void](Label '采集、处理与材料交接' 32 70 500 26 10)
[void](Label '录音与转写' 32 125 220 28 12 $true)
$recordState=Label '未启动' 32 157 310 24 10
$recordStart=Button '开始录音' 410 125 112; $recordStop=Button '停止' 536 125 112
[void](Label '材料网关' 32 223 220 28 12 $true)
$gatewayState=Label '未启动' 32 255 310 24 10
$gatewayStart=Button '启动网关' 410 223 112; $gatewayStop=Button '停止' 536 223 112
[void](Label '录像截图与 OCR' 32 321 250 28 12 $true)
$visualState=Label '未启动' 32 353 340 24 10
$visualStart=Button '启动处理' 410 321 112; $visualStop=Button '停止' 536 321 112
$openData=Button '打开资料目录' 32 424 150
$openLogs=Button '打开日志' 194 424 115
$message=Label '关闭窗口时会请求停止已启动的功能。' 324 432 340 40 9
function Add-Component($id,$scriptName,$state,$start,$stop,$extra){
 $script:components[$id]=@{Name=$scriptName;State=$state;Start=$start;Stop=$stop;Extra=$extra;Process=$null;Stopping=$false;StopFile=(Join-Path $stopRoot ($id+'.stop'));Log=(Join-Path $root ('out\ui\'+$id+'.log'))}
 $stop.Enabled=$false
}
Add-Component 'record' 'run_core.py' $recordState $recordStart $recordStop @()
Add-Component 'gateway' 'ai_material_gateway.py' $gatewayState $gatewayStart $gatewayStop @('serve')
Add-Component 'visual' 'visual_worker.py' $visualState $visualStart $visualStop @('--watch')
function Start-Component([string]$id){
 $item=$script:components[$id]
 if($item.Process -and -not $item.Process.HasExited){return}
 if(-not (Test-Path -LiteralPath $python)){[Windows.Forms.MessageBox]::Show('环境尚未安装，请先运行安装程序。','录音记忆') | Out-Null;return}
 try {
  if(Test-Path -LiteralPath $item.StopFile){[IO.File]::Delete($item.StopFile)}
  $launcher=Join-Path $root 'module_launcher.py'; $target=Join-Path $root $item.Name
  $parts=@(('"'+$launcher+'"'),'--log',('"'+$item.Log+'"'),('"'+$target+'"')) + $item.Extra + @('--stop-file',('"'+$item.StopFile+'"'))
  $info=New-Object Diagnostics.ProcessStartInfo; $info.FileName=$python; $info.Arguments=$parts -join ' '
  $info.WorkingDirectory=$root; $info.UseShellExecute=$false; $info.CreateNoWindow=$true
  $item.Process=[Diagnostics.Process]::Start($info); $item.Stopping=$false
  $item.State.Text='正在启动'; $item.Start.Enabled=$false; $item.Stop.Enabled=$true
 } catch { $item.State.Text='启动失败'; $message.Text='请检查安装和日志。' }
}
function Stop-Component([string]$id){
 $item=$script:components[$id]
 if($item.Process -and -not $item.Process.HasExited){
  [IO.File]::WriteAllText($item.StopFile,'stop'); $item.Stopping=$true
  $item.State.Text=if($id -eq 'visual'){'等待当前视频处理结束'}else{'正在停止，请稍候'}; $item.Stop.Enabled=$false
 }
}
$recordStart.Add_Click({Start-Component 'record'});$recordStop.Add_Click({Stop-Component 'record'})
$gatewayStart.Add_Click({Start-Component 'gateway'});$gatewayStop.Add_Click({Stop-Component 'gateway'})
$visualStart.Add_Click({Start-Component 'visual'});$visualStop.Add_Click({Stop-Component 'visual'})
$openData.Add_Click({$path=Join-Path $root 'out';[void][IO.Directory]::CreateDirectory($path);[Diagnostics.Process]::Start('explorer.exe',$path) | Out-Null})
$openLogs.Add_Click({$path=Join-Path $root 'out\ui';[void][IO.Directory]::CreateDirectory($path);[Diagnostics.Process]::Start('explorer.exe',$path) | Out-Null})
$timer=New-Object Windows.Forms.Timer; $timer.Interval=700
$timer.Add_Tick({
 $running=$false
 foreach($item in $script:components.Values){
  if(-not $item.Process){continue}
  if($item.Process.HasExited){
   $code=$item.Process.ExitCode
   $item.State.Text=if($item.Stopping -or $code -eq 0){'已停止'}else{'已退出，查看日志'}
   $item.Process.Dispose();$item.Process=$null;$item.Stopping=$false;$item.Start.Enabled=-not $script:closing;$item.Stop.Enabled=$false
  }else{$running=$true;if(-not $item.Stopping){$item.State.Text='进程运行中'}}
 }
 if($script:closing -and -not $running){$script:allowClose=$true;$form.Close()}
})
$form.Add_FormClosing({param($sender,$eventArgs)
 if($script:allowClose){return}
 $active=@($script:components.Keys | Where-Object {$script:components[$_].Process -and -not $script:components[$_].Process.HasExited})
 if($active.Count){
  $eventArgs.Cancel=$true;$script:closing=$true;$message.Text='正在保存并停止已启动的功能，请稍候。'
  foreach($id in $active){Stop-Component $id};foreach($item in $script:components.Values){$item.Start.Enabled=$false}
 }else{$script:allowClose=$true}
})
if($env:AUDIO_MEMORY_UI_TEST -eq '1'){
 $form.StartPosition='Manual';$form.Location=New-Object Drawing.Point(-2000,-2000);$form.Show();[Windows.Forms.Application]::DoEvents()
 $listener=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0);$listener.Start();$port=([Net.IPEndPoint]$listener.LocalEndpoint).Port;$listener.Stop()
 $script:components['gateway'].Extra=@('serve','--port',[string]$port)
 try{
  $gatewayStart.PerformClick();$item=$script:components['gateway'];if(-not $item.Process){throw 'Gateway button did not start a process'}
  $tokenFile=Join-Path $root 'out\ai-gateway\access-token';$deadline=[DateTime]::UtcNow.AddSeconds(20);$ok=$false
  while([DateTime]::UtcNow -lt $deadline -and -not $item.Process.HasExited){
   [Windows.Forms.Application]::DoEvents()
   try{
    $key=[IO.File]::ReadAllText($tokenFile).Trim()
    $reply=Invoke-RestMethod -Uri ('http://127.0.0.1:'+$port+'/v1/health') -Headers @{Authorization=('Bearer '+$key)} -TimeoutSec 1
    if($reply.ok){$ok=$true;break}
   }catch{};Start-Sleep -Milliseconds 200
  }
  if(-not $ok){throw 'Gateway did not become ready'}
  if($env:AUDIO_MEMORY_UI_TEST_ISOLATION -eq '1'){
   $visualStart.PerformClick();$visualItem=$script:components['visual']
   if(-not $visualItem.Process){throw 'Visual button did not start a process'}
   Start-Sleep -Milliseconds 500
   if($visualItem.Process.HasExited){throw 'Visual process exited early'}
   $gatewayStop.PerformClick()
   if(-not $item.Process.WaitForExit(10000)){throw 'Gateway did not stop'}
   if($visualItem.Process.HasExited){throw 'Stopping gateway stopped visual unit'}
   $visualStop.PerformClick()
   if(-not $visualItem.Process.WaitForExit(10000)){throw 'Visual process did not stop'}
   Write-Output 'PASS: gateway and visual units stop independently'
  }elseif($env:AUDIO_MEMORY_UI_TEST_CLOSE -eq '1'){
   $timer.Start();$form.Close();$deadline=[DateTime]::UtcNow.AddSeconds(15)
   while(-not $form.IsDisposed -and [DateTime]::UtcNow -lt $deadline){[Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 100}
   $timer.Stop();if(-not $form.IsDisposed){throw 'Window did not close after stopping'}
   Write-Output 'PASS: closing the window stops its gateway and closes'
  }else{
   $gatewayStop.PerformClick();if(-not $item.Stopping){throw 'Stop button did not request stop'}
   $item.Process.WaitForExit(10000) | Out-Null
   if(-not $item.Process.HasExited){throw 'Gateway did not stop'}
   if($item.Process.ExitCode -ne 0){throw 'Gateway exited with an error'}
   Write-Output 'PASS: gateway button starts authenticated service and stop button exits it'
  }
 }finally{
  foreach($id in $script:components.Keys){
   $item=$script:components[$id]
   if($item.Process -and -not $item.Process.HasExited){Stop-Component $id;if(-not $item.Process.WaitForExit(10000)){$item.Process.Kill();$item.Process.WaitForExit()}}
   if($item.Process){$item.Process.Dispose();$item.Process=$null}
  }
  $form.Dispose()
 }
}elseif($Preview){
 $form.StartPosition='Manual';$form.Location=New-Object Drawing.Point(-2000,-2000);$form.Show();[Windows.Forms.Application]::DoEvents()
 $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
 $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$bitmap.Width,$bitmap.Height)))
 $bitmap.Save($Preview,[Drawing.Imaging.ImageFormat]::Png);$bitmap.Dispose();$form.Dispose()
}else{
 $timer.Start();[void]$form.ShowDialog();$timer.Stop();$timer.Dispose();$form.Dispose()
}
foreach($item in $script:components.Values){try{[IO.File]::Delete($item.StopFile)}catch{}}
try{[IO.Directory]::Delete($stopRoot,$false)}catch{}
