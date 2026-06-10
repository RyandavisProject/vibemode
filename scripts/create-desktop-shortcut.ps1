param(
    [string]$ShortcutName = "NeuroGate API",
    [string]$DesktopDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RunScript = Join-Path $Root "scripts\run-overlay.ps1"
$Desktop = if ($DesktopDir) { $DesktopDir } else { [Environment]::GetFolderPath("Desktop") }
New-Item -ItemType Directory -Path $Desktop -Force | Out-Null
$ShortcutPath = Join-Path $Desktop "$ShortcutName.lnk"

if ($ShortcutName -eq "NeuroGate API") {
    @("Vibemode Overlay.lnk", "Neurogate Usage Overlay.lnk") |
        ForEach-Object {
            $OldShortcutPath = Join-Path $Desktop $_
            if (Test-Path $OldShortcutPath) {
                Remove-Item -LiteralPath $OldShortcutPath -Force
            }
        }
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "Start the NeuroGate API limits overlay"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
$Shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath"
