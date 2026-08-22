@echo off
setlocal
cd /d "%~dp0"
title Threaded Insert Hardware Library Editor

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0hardware_library_editor_server.ps1"
if errorlevel 1 pause
exit /b %errorlevel%
