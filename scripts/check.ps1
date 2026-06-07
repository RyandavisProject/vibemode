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
} finally {
    Pop-Location
}
