param(
    [string]$TaskName = "QuantGenerated Live Health Report",
    [string]$Time = "23:55"
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_live_health_report.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Runner script not found: $scriptPath"
}

$parts = $Time.Split(":")
if ($parts.Count -ne 2) {
    throw "Time must be in HH:mm format."
}

$hour = [int]$parts[0]
$minute = [int]$parts[1]
$startTime = (Get-Date).Date.AddHours($hour).AddMinutes($minute)
if ($startTime -lt (Get-Date)) {
    $startTime = $startTime.AddDays(1)
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $startTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Generate QuantGenerated live health report each day." `
    -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName at $Time"
