param(
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv"
$Python = "python"

if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e $Root

if (-not $NoShortcut) {
    & (Join-Path $Root "scripts\create-desktop-shortcut.ps1")
}

Write-Host ""
Write-Host "Installed Vibemode Overlay."
Write-Host "Run: .\scripts\run-overlay.ps1"
