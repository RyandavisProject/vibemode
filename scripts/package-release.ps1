param(
    [string]$Version = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "dist"
}

if (-not $Version) {
    $VersionLine = Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=' | Select-Object -First 1
    if (-not $VersionLine) {
        throw "Cannot detect project version from pyproject.toml."
    }
    $Version = ($VersionLine.Line -replace 'version\s*=\s*"', '').Trim('"')
}

$PackageName = "neurogate-overlay-v$Version"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "neurogate-overlay-package-$([System.Guid]::NewGuid())"
$Stage = Join-Path $TempRoot $PackageName
$ZipPath = Join-Path $OutputDir "$PackageName.zip"
$SkipDirs = @(".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build")
$SkipFilePatterns = @("*.pyc", "*.pyo", "*.pyd", "*.log", "*.trace.zip", "*.har", "*.cookies", "*.local.json")

function Test-SkippedFile($Name) {
    foreach ($Pattern in $SkipFilePatterns) {
        if ($Name -like $Pattern) {
            return $true
        }
    }
    return $false
}

function Copy-PackageTree($Source, $Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force |
        ForEach-Object {
            if ($_.PSIsContainer) {
                if ($SkipDirs -contains $_.Name -or $_.Name.EndsWith(".egg-info")) {
                    return
                }
                Copy-PackageTree $_.FullName (Join-Path $Destination $_.Name)
            } else {
                if (Test-SkippedFile $_.Name) {
                    return
                }
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $_.Name) -Force
            }
        }
}

try {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Copy-PackageTree $Root $Stage
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -Path $Stage -DestinationPath $ZipPath -Force
    Write-Host "Release ZIP created: $ZipPath"
} finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
