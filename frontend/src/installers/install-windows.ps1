$ErrorActionPreference = 'Stop'
try {
$dir = Join-Path $env:LOCALAPPDATA 'ProxyLens'
$taskName = 'ProxyLens Agent'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (!(Test-Path "$PSScriptRoot\agent.json") -or !(Test-Path "$PSScriptRoot\proxylens-agent.exe")) { throw '请先解压完整安装包。' }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
# Apply inheritable permissions only to the directory. Removing inheritance
# recursively can leave existing files with an empty ACL.
& icacls.exe $dir /inheritance:r /grant:r "*${userSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw '无法设置安装目录权限。' }
Get-ChildItem -LiteralPath $dir -Force | ForEach-Object {
    & icacls.exe $_.FullName /reset /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '无法恢复已安装文件的权限。' }
}
Start-Transcript -Path "$dir\install.log" -Force | Out-Null
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $taskName }
Copy-Item "$PSScriptRoot\proxylens-agent.exe" "$dir\proxylens-agent.exe" -Force
Copy-Item "$PSScriptRoot\agent.json" "$dir\agent.json" -Force
Unblock-File "$dir\proxylens-agent.exe"
Write-Host '正在检查 Agent 并执行首次上报，请稍候…'
$check = Start-Process -FilePath "$dir\proxylens-agent.exe" -ArgumentList "-config `"$dir\agent.json`" -once" -WorkingDirectory $dir -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$dir\first-report.log" -RedirectStandardError "$dir\first-report-error.log"
if ($check.ExitCode -ne 0) {
    Get-Content "$dir\first-report-error.log" -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    throw '首次上报失败，请检查上报地址、网络和设备凭证。'
}
Write-Host '首次上报成功，正在注册后台服务。'
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

Start-Sleep -Seconds 3
$info = Get-ScheduledTaskInfo -TaskName $taskName
$state = (Get-ScheduledTask -TaskName $taskName).State
if ($state -ne 'Running') {
    throw "后台任务未持续运行（结果：$($info.LastTaskResult)），请查看 agent-error.log。"
}
Write-Host '安装完成：Agent 已静默运行，登录后自动启动，关闭此窗口不会停止上报。'
Write-Host "安装日志：$dir\install.log"
Stop-Transcript | Out-Null
exit 0
} catch {
    Write-Host ("安装失败：" + $_.Exception.Message) -ForegroundColor Red
    Write-Host '请把窗口中的错误信息发给管理员，或查看 %LOCALAPPDATA%\ProxyLens\install.log。'
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    exit 1
}
