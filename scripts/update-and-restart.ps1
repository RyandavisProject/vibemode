param(
    [string]$TargetVersion = "",
    [switch]$NoRestart,
    [switch]$NoShortcut,
    [switch]$AllowUnverifiedZip,
    [string]$ShortcutDir = "",
    [string]$ReleaseZipUrl = "",
    [string]$ReleaseSha256 = ""
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

function Normalize-Sha256($Value) {
    if (-not $Value) {
        return ""
    }
    $FirstToken = ($Value -split '\s+')[0]
    return $FirstToken.Trim().ToLowerInvariant()
}

function Get-ReleaseSha256($ArchiveUrl, $ZipPath) {
    if ($ReleaseSha256) {
        return Normalize-Sha256 $ReleaseSha256
    }
    if ($env:NEUROGATE_UPDATE_SHA256) {
        return Normalize-Sha256 $env:NEUROGATE_UPDATE_SHA256
    }

    $SidecarPath = "$ZipPath.sha256"
    if (Test-Path $ArchiveUrl) {
        $LocalSidecar = "$ArchiveUrl.sha256"
        if (Test-Path $LocalSidecar) {
            Copy-Item -LiteralPath $LocalSidecar -Destination $SidecarPath -Force
            return Normalize-Sha256 (Get-Content -LiteralPath $SidecarPath -Raw)
        }
        return ""
    }

    try {
        Invoke-WebRequest -Uri "$ArchiveUrl.sha256" -OutFile $SidecarPath -UseBasicParsing
        return Normalize-Sha256 (Get-Content -LiteralPath $SidecarPath -Raw)
    } catch {
        return ""
    }
}

function Confirm-ReleaseSha256($ZipPath, $ExpectedHash) {
    $Expected = Normalize-Sha256 $ExpectedHash
    if (-not $Expected) {
        if ($AllowUnverifiedZip -or $env:NEUROGATE_ALLOW_UNVERIFIED_UPDATE -eq "1") {
            Write-Host "SHA256 checksum was not provided; continuing because unverified ZIP updates were explicitly allowed." -ForegroundColor Yellow
            return
        }
        throw "SHA256 checksum is required for ZIP updates. Attach a .sha256 sidecar, pass -ReleaseSha256, or use -AllowUnverifiedZip only for local development."
    }
    if ($Expected -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA256 checksum format."
    }
    $Actual = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) {
        throw "ZIP checksum mismatch. Expected $Expected but got $Actual."
    }
    Write-Step "ZIP checksum verified."
}

function Assert-UnderDirectory($Path, $Directory) {
    $Base = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $Full = [System.IO.Path]::GetFullPath($Path)
    if (-not ($Full.Equals($Base, [System.StringComparison]::OrdinalIgnoreCase) -or $Full.StartsWith("$Base\", [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing to modify path outside project directory: $Full"
    }
}

function Copy-ReleaseItem($Source, $Destination, $TargetDir) {
    Assert-UnderDirectory $Destination $TargetDir
    $Parent = Split-Path -Parent $Destination
    if ($Parent) {
        New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    }
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Restore-ReleaseBackup($BackupDir, $TargetDir, [string[]]$TouchedItems) {
    foreach ($Name in $TouchedItems) {
        $Destination = Join-Path $TargetDir $Name
        Assert-UnderDirectory $Destination $TargetDir
        if (Test-Path $Destination) {
            Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
        }
        $BackupItem = Join-Path $BackupDir $Name
        if (Test-Path $BackupItem) {
            Copy-Item -LiteralPath $BackupItem -Destination $Destination -Recurse -Force
        }
    }
}

function Copy-ReleaseTree($SourceDir, $TargetDir) {
    $AllowedItems = @(
        "src",
        "scripts",
        "docs",
        "tests",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "SECURITY.md",
        "pyproject.toml",
        "Install-Vibemod.bat"
        "Install-NeuroGate-API.bat"
    )
    $BackupDir = Join-Path ([System.IO.Path]::GetTempPath()) "vibemod-backup-$([System.Guid]::NewGuid())"
    $TouchedItems = New-Object System.Collections.Generic.List[string]

    try {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
        foreach ($Name in $AllowedItems) {
            $Source = Join-Path $SourceDir $Name
            if (-not (Test-Path $Source)) {
                continue
            }
            $Destination = Join-Path $TargetDir $Name
            Assert-UnderDirectory $Destination $TargetDir
            $TouchedItems.Add($Name)
            if (Test-Path $Destination) {
                Copy-Item -LiteralPath $Destination -Destination (Join-Path $BackupDir $Name) -Recurse -Force
            }
            Copy-ReleaseItem $Source $Destination $TargetDir
        }
    } catch {
        Write-Host "Rolling back ZIP update..." -ForegroundColor Yellow
        Restore-ReleaseBackup $BackupDir $TargetDir $TouchedItems.ToArray()
        throw
    } finally {
        if (Test-Path $BackupDir) {
            Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
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

    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "vibemod-update-$([System.Guid]::NewGuid())"
    $ZipPath = Join-Path $TempRoot "release.zip"
    $ExtractPath = Join-Path $TempRoot "extract"
    $ArchiveUrl = if ($ReleaseZipUrl) {
        $ReleaseZipUrl
    } elseif ($env:NEUROGATE_UPDATE_ZIP_URL) {
        $env:NEUROGATE_UPDATE_ZIP_URL
    } else {
        "https://github.com/RyandavisProject/vibemod/archive/refs/tags/$VersionTag.zip"
    }

    try {
        New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
        Write-Step "Loading $VersionTag ZIP package..."
        if (Test-Path $ArchiveUrl) {
            Copy-Item -LiteralPath $ArchiveUrl -Destination $ZipPath -Force
        } else {
            Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ZipPath -UseBasicParsing
        }
        Confirm-ReleaseSha256 $ZipPath (Get-ReleaseSha256 $ArchiveUrl $ZipPath)

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
    Write-Host "Updating Vibemod overlay..."
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
