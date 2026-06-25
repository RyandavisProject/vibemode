@echo off
setlocal
cd /d "%~dp0"

set "INSTALL_ARGS="
if defined NEUROGATE_SHORTCUT_DIR set "INSTALL_ARGS=%INSTALL_ARGS% -ShortcutDir ""%NEUROGATE_SHORTCUT_DIR%"""

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %INSTALL_ARGS%
if errorlevel 1 (
    echo.
    echo Installation failed. Check the message above.
    if not defined NEUROGATE_INSTALL_NO_PAUSE pause
    exit /b 1
)

echo.
echo Vibemod installed.
echo Desktop shortcut: Vibemod
if not defined NEUROGATE_INSTALL_NO_PAUSE pause
