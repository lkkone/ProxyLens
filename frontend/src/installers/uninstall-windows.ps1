$ErrorActionPreference = 'Stop'
$taskName = 'ProxyLens Agent'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Remove-Item (Join-Path $env:LOCALAPPDATA 'ProxyLens') -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'ProxyLens Agent 已停止并卸载。'
