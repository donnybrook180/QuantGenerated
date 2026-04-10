$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "artifacts\system\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "live_health_report_$timestamp.log"
$today = (Get-Date).Date
$liveArtifactsDir = Join-Path $repoRoot "artifacts\live"
$reportPath = Join-Path $repoRoot "artifacts\system\reports\live_health_report.txt"

function Test-LiveLoopRunning {
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { ($_.CommandLine -as [string]) -like "*main_live_loop.py*" }
    return [bool]$processes
}

function Test-LiveRanToday {
    if (-not (Test-Path -LiteralPath $liveArtifactsDir)) {
        return $false
    }
    $journals = Get-ChildItem -Path $liveArtifactsDir -Recurse -Filter "*_journal.json" -File -ErrorAction SilentlyContinue
    foreach ($journal in ($journals | Where-Object { $_.LastWriteTime.Date -eq $today })) {
        try {
            $payload = Get-Content -LiteralPath $journal.FullName -Raw | ConvertFrom-Json
            if ($null -ne $payload.actions -and $payload.actions.Count -gt 0) {
                return $true
            }
        }
        catch {
        }
    }
    $incidents = Get-ChildItem -Path $liveArtifactsDir -Recurse -Filter "*_incident.txt" -File -ErrorAction SilentlyContinue
    return [bool]($incidents | Where-Object { $_.LastWriteTime.Date -eq $today } | Select-Object -First 1)
}

function Get-LatestLiveActivityTime {
    if (-not (Test-Path -LiteralPath $liveArtifactsDir)) {
        return $null
    }
    $latestJournalActivity = $null
    $journals = Get-ChildItem -Path $liveArtifactsDir -Recurse -Filter "*_journal.json" -File -ErrorAction SilentlyContinue
    foreach ($journal in ($journals | Where-Object { $_.LastWriteTime.Date -eq $today })) {
        try {
            $payload = Get-Content -LiteralPath $journal.FullName -Raw | ConvertFrom-Json
            if ($null -ne $payload.actions -and $payload.actions.Count -gt 0) {
                if ($null -eq $latestJournalActivity -or $journal.LastWriteTime -gt $latestJournalActivity) {
                    $latestJournalActivity = $journal.LastWriteTime
                }
            }
        }
        catch {
        }
    }
    $latestIncident = Get-ChildItem -Path $liveArtifactsDir -Recurse -Filter "*_incident.txt" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime.Date -eq $today } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $latestJournalActivity) {
        return $latestIncident.LastWriteTime
    }
    if ($null -eq $latestIncident) {
        return $latestJournalActivity
    }
    if ($latestIncident.LastWriteTime -gt $latestJournalActivity) {
        return $latestIncident.LastWriteTime
    }
    return $latestJournalActivity
}

$liveLoopRunning = Test-LiveLoopRunning
$liveRanToday = Test-LiveRanToday
$latestLiveActivityTime = Get-LatestLiveActivityTime
$lastReportTime = if (Test-Path -LiteralPath $reportPath) { (Get-Item -LiteralPath $reportPath).LastWriteTime } else { $null }

Push-Location $repoRoot
try {
    if (-not $liveLoopRunning -and -not $liveRanToday) {
        "Skipped live health report: live loop not active and no actionable journals or incidents written today." |
            Tee-Object -FilePath $logPath
        return
    }
    if (-not $liveLoopRunning -and $null -ne $lastReportTime -and $null -ne $latestLiveActivityTime -and $lastReportTime -ge $latestLiveActivityTime) {
        "Skipped live health report: no new live activity since the last report." |
            Tee-Object -FilePath $logPath
        return
    }
    & python "tools\main_live_health_report.py" *>&1 | Tee-Object -FilePath $logPath
}
finally {
    Pop-Location
}
