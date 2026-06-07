$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$ProfilePath = Join-Path $env:USERPROFILE ".neurogate-usage-overlay\browser-profile"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtual environment not found. Installing first..."
    & (Join-Path $Root "scripts\install.ps1")
}

# Keep one overlay instance. Multiple instances fight for the same Chrome
# profile and can show empty values. Do not match PowerShell/cmd launchers here:
# parent shells can contain this project path in their command line.
Get-CimInstance Win32_Process |
    Where-Object {
        (
            ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'neurogate_usage_overlay') -or
            ($_.Name -eq 'node.exe' -and $_.CommandLine -match [regex]::Escape($Root)) -or
            ($_.Name -eq 'chrome.exe' -and $_.CommandLine -match [regex]::Escape($ProfilePath))
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

& $VenvPython -m neurogate_usage_overlay --interval 60
