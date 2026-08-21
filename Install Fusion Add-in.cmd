@echo off
setlocal
cd /d "%~dp0"
title Heat Insert Connections - Install Fusion Add-in

echo Installing Heat Insert Connections into the current user's Fusion 360 Add-ins folder...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-FusionAddIn.ps1" -Clean
if errorlevel 1 (
    echo.
    echo Installation failed. Review the message above.
    pause
    exit /b 1
)

echo.
echo Installation completed.
echo If Fusion 360 is already running, reload FusionHeatInsertAddIn from Utilities ^> Scripts and Add-Ins.
pause
