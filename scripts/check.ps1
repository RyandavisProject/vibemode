$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Push-Location $Root
try {
    & $Python -m compileall src tests
    $env:PYTHONPATH = Join-Path $Root "src"
    & $Python -m unittest discover -s tests -v
    Get-ChildItem -LiteralPath (Join-Path $Root "scripts") -Filter "*.ps1" |
        ForEach-Object {
            $Tokens = $null
            $ParseErrors = $null
            [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$Tokens, [ref]$ParseErrors) | Out-Null
            if ($ParseErrors) {
                throw "PowerShell syntax check failed for $($_.Name): $($ParseErrors[0].Message)"
            }
        }
} finally {
    Pop-Location
}
