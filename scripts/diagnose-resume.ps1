param(
    [string]$StateDir = (Join-Path $env:USERPROFILE ".neurogate-usage-overlay"),
    [int]$Tail = 300
)

$ErrorActionPreference = "Stop"

$UiLog = Join-Path $StateDir "overlay-ui.log"
$DebugLog = Join-Path $StateDir "overlay-debug.log"

function Read-RecentLines($Path, $Count) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Encoding UTF8 -Tail $Count)
}

function Get-LineTime($Line) {
    if ($Line -match "^(?<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})") {
        return [datetime]::Parse($Matches.ts)
    }
    return $null
}

function Get-SnapshotSignature($Line) {
    if ($Line -notmatch "\bsnapshot\b") {
        return $null
    }
    $parts = @()
    foreach ($Pattern in @(
        "5h:remaining=(?<value>[-\d]+)",
        "5h:remaining=[-\d]+ used=(?<value>[-\d]+)",
        "7d:remaining=(?<value>[-\d]+)",
        "7d:remaining=[-\d]+ used=(?<value>[-\d]+)",
        "daily_spent=(?<value>[-\d]+)"
    )) {
        if ($Line -match $Pattern) {
            $parts += $Matches.value
        } else {
            $parts += "?"
        }
    }
    return ($parts -join "|")
}

$uiLines = Read-RecentLines $UiLog $Tail
$debugLines = Read-RecentLines $DebugLog $Tail
$resumeLine = $uiLines | Where-Object { $_ -match "resume_gap_detected|resume_recovery_requested|power_resume|windows_power_resume|macos_workspace_wake" } | Select-Object -Last 1

if (-not $resumeLine) {
    Write-Host "Resume diagnostics: no recent resume event found in overlay-ui.log"
    exit 0
}

$resumeTime = Get-LineTime $resumeLine
$afterResume = @($uiLines | Where-Object {
    $lineTime = Get-LineTime $_
    $lineTime -and $resumeTime -and $lineTime -ge $resumeTime
})

$snapshotLines = @($afterResume | Where-Object { $_ -match "\bsnapshot\b" })
$latestSignatures = @($snapshotLines | ForEach-Object { Get-SnapshotSignature $_ } | Where-Object { $_ })
$latestSignature = $latestSignatures | Select-Object -Last 1
$sameTailCount = 0
if ($latestSignature) {
    for ($index = $latestSignatures.Count - 1; $index -ge 0; $index--) {
        if ($latestSignatures[$index] -ne $latestSignature) {
            break
        }
        $sameTailCount += 1
    }
}

$forcedRefreshCount = @($afterResume | Where-Object { $_ -match "refresh_started force=True|refresh_requested force=True" }).Count
$skippedRefreshCount = @($afterResume | Where-Object { $_ -match "refresh_skipped" }).Count
$heldCount = @($afterResume | Where-Object { $_ -match "low_confidence_snapshot_held|incomplete_snapshot_held|transient_failure_held" }).Count
$recoveryLines = @($debugLines | Where-Object {
    $lineTime = Get-LineTime $_
    $lineTime -and $resumeTime -and $lineTime -ge $resumeTime -and $_ -match "hidden_session_recovery_(start|done|error)"
})

Write-Host "Resume diagnostics"
Write-Host "resume: $resumeLine"
Write-Host "snapshots after resume: $($snapshotLines.Count)"
Write-Host "forced refresh events after resume: $forcedRefreshCount"
Write-Host "skipped refresh events after resume: $skippedRefreshCount"
Write-Host "held suspicious snapshots after resume: $heldCount"
Write-Host "hidden recovery events after resume: $($recoveryLines.Count)"
Write-Host "latest repeated snapshot count: $sameTailCount"

if ($sameTailCount -ge 3) {
    Write-Host "status: WARN repeated identical snapshots after resume"
    exit 2
}

if ($snapshotLines.Count -eq 0) {
    Write-Host "status: WARN no snapshots after resume"
    exit 2
}

Write-Host "status: OK no repeated snapshot tail detected"
