$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'ProxyLens'
$taskName = 'ProxyLens Agent'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if (!(Test-Path "$PSScriptRoot\agent.json") -or !(Test-Path "$PSScriptRoot\proxylens-agent.exe")) { throw '请先解压完整安装包。' }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $taskName }
Copy-Item "$PSScriptRoot\proxylens-agent.exe" "$dir\proxylens-agent.exe" -Force
Copy-Item "$PSScriptRoot\agent.json" "$dir\agent.json" -Force
Unblock-File "$dir\proxylens-agent.exe"
# Restrict the configuration and executable to the current user and SYSTEM.
& icacls.exe $dir /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw '无法设置配置文件权限。' }
$runner = @'
$dir = $PSScriptRoot
$p = Start-Process -FilePath "$dir\proxylens-agent.exe" -ArgumentList "-config `"$dir\agent.json`"" -WorkingDirectory $dir -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$dir\agent.log" -RedirectStandardError "$dir\agent-error.log"
exit $p.ExitCode
'@
Set-Content -LiteralPath "$dir\run-agent.ps1" -Value $runner -Encoding UTF8
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dir\run-agent.ps1`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host '安装完成：Agent 已静默运行，登录后自动启动，关闭窗口不会停止上报。'
