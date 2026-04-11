param(
    [string]$TaskName = "QuantGenerated Live Loop",
    [ValidateSet("AtLogon", "AtStartup")]
    [string]$TriggerType = "AtLogon",
    [int]$RestartDelaySeconds = 15,
    [int]$MaxRestarts = 0
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_live_loop_supervised.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Runner script not found: $scriptPath"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RestartDelaySeconds $RestartDelaySeconds -MaxRestarts $MaxRestarts"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $argument

if ($TriggerType -eq "AtStartup") {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $description = "Start QuantGenerated supervised live loop at Windows startup."
}
else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $description = "Start QuantGenerated supervised live loop at user logon."
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description $description `
    -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName ($TriggerType)"
