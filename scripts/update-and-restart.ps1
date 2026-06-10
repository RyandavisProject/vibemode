param(
    [string]$TargetVersion = "",
    [switch]$NoRestart,
    [switch]$NoShortcut,
    [string]$ShortcutDir = "",
    [string]$ReleaseZipUrl = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$RunScript = Join-Path $Root "scripts\run-overlay.ps1"
$InstallScript = Join-Path $Root "scripts\install.ps1"
$ShortcutScript = Join-Path $Root "scripts\create-desktop-shortcut.ps1"

function Write-Step($Message) {
    Write-Host ""
    Write-Host $Message
}

function Invoke-Native($Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

function Copy-ReleaseTree($SourceDir, $TargetDir) {
    $SkipNames = @(".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build")
    Get-ChildItem -LiteralPath $SourceDir -Force |
        Where-Object { $SkipNames -notcontains $_.Name } |
        ForEach-Object {
            $Destination = Join-Path $TargetDir $_.Name
            if ($_.PSIsContainer) {
                if (Test-Path $Destination) {
                    Remove-Item -LiteralPath $Destination -Recurse -Force
                }
                Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
            } else {
                Copy-Item -LiteralPath $_.FullName -Destination $Destination -Force
            }
        }
}

function Update-FromGit {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or is not available in PATH."
    }

    $Dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed with exit code $LASTEXITCODE."
    }
    if ($Dirty) {
        throw "Local files were changed. Automatic update stopped to avoid overwriting user changes."
    }

    Write-Step "Fetching updates from GitHub..."
    Invoke-Native "git" @("fetch", "origin", "main")

    Write-Step "Applying update..."
    Invoke-Native "git" @("pull", "--ff-only", "origin", "main")
}

function Update-FromZipRelease {
    if (-not $TargetVersion) {
        throw "Target version is required for ZIP-based updates."
    }

    $VersionTag = $TargetVersion
    if (-not $VersionTag.StartsWith("v")) {
        $VersionTag = "v$VersionTag"
    }

    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "neurogate-overlay-update-$([System.Guid]::NewGuid())"
    $ZipPath = Join-Path $TempRoot "release.zip"
    $ExtractPath = Join-Path $TempRoot "extract"
    $ArchiveUrl = if ($ReleaseZipUrl) {
        $ReleaseZipUrl
    } elseif ($env:NEUROGATE_UPDATE_ZIP_URL) {
        $env:NEUROGATE_UPDATE_ZIP_URL
    } else {
        "https://github.com/RyandavisProject/neurogate-overlay/archive/refs/tags/$VersionTag.zip"
    }

    try {
        New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
        Write-Step "Loading $VersionTag ZIP package..."
        if (Test-Path $ArchiveUrl) {
            Copy-Item -LiteralPath $ArchiveUrl -Destination $ZipPath -Force
        } else {
            Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ZipPath -UseBasicParsing
        }

        Write-Step "Extracting update..."
        Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractPath -Force
        $ReleaseRoot = Get-ChildItem -LiteralPath $ExtractPath -Directory | Select-Object -First 1
        if (-not $ReleaseRoot) {
            throw "Downloaded ZIP does not contain a project folder."
        }

        Write-Step "Applying ZIP update..."
        Copy-ReleaseTree $ReleaseRoot.FullName $Root
    } finally {
        if (Test-Path $TempRoot) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Push-Location $Root
try {
    Write-Host "Updating NeuroGate API overlay..."
    if ($TargetVersion) {
        Write-Host "Target version: $TargetVersion"
    }

    if (Test-Path ".git") {
        Update-FromGit
    } else {
        Update-FromZipRelease
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Step "Virtual environment not found. Running installer..."
        & $InstallScript -NoShortcut
    } else {
        Write-Step "Updating Python package..."
        Invoke-Native $VenvPython @("-m", "pip", "install", "-e", $Root)
    }

    if (-not $NoShortcut) {
        Write-Step "Updating desktop shortcut..."
        if ($ShortcutDir) {
            & $ShortcutScript -DesktopDir $ShortcutDir
        } else {
            & $ShortcutScript
        }
    }

    if (-not $NoRestart) {
        Write-Step "Starting updated overlay..."
        Start-Process powershell.exe -ArgumentList @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $RunScript
        ) -WorkingDirectory $Root
    }

    Write-Step "Update completed."
} catch {
    Write-Host ""
    Write-Host "Update failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
