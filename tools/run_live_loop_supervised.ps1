$ErrorActionPreference = "Stop"

param(
    [int]$RestartDelaySeconds = 15,
    [int]$MaxRestarts = 0,
    [switch]$Once
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$mainScript = Join-Path $repoRoot "main_live_loop.py"
$logDir = Join-Path $repoRoot "artifacts\system\logs"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath $mainScript)) {
    throw "Live loop entrypoint not found: $mainScript"
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$restartCount = 0

while ($true) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutPath = Join-Path $logDir "live_loop_$timestamp.out.log"
    $stderrPath = Join-Path $logDir "live_loop_$timestamp.err.log"

    "[$(Get-Date -Format s)] starting live loop (restart=$restartCount)" | Tee-Object -FilePath $stdoutPath -Append | Out-Null

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($mainScript) `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru `
        -Wait `
        -NoNewWindow

    $exitCode = $process.ExitCode
    $endedAt = Get-Date -Format s
    "[$endedAt] live loop exited with code $exitCode" | Tee-Object -FilePath $stdoutPath -Append | Out-Null

    if ($Once) {
        exit $exitCode
    }

    $restartCount += 1
    if ($MaxRestarts -gt 0 -and $restartCount -ge $MaxRestarts) {
        "[$endedAt] reached MaxRestarts=$MaxRestarts, stopping supervisor" | Tee-Object -FilePath $stdoutPath -Append | Out-Null
        exit $exitCode
    }

    Start-Sleep -Seconds ([Math]::Max($RestartDelaySeconds, 5))
}
