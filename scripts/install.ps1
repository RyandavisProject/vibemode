param(
    [switch]$NoShortcut,
    [string]$ShortcutDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv"
$Python = "python"

function Invoke-Native($Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $Venv)) {
    Invoke-Native $Python @("-m", "venv", $Venv)
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
Invoke-Native $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Native $VenvPython @("-m", "pip", "install", "-e", $Root)

if (-not $NoShortcut) {
    $ShortcutScript = Join-Path $Root "scripts\create-desktop-shortcut.ps1"
    if ($ShortcutDir) {
        & $ShortcutScript -DesktopDir $ShortcutDir
    } else {
        & $ShortcutScript
    }
}

Write-Host ""
Write-Host "Installed Vibemod."
Write-Host "Run: .\scripts\run-overlay.ps1"
