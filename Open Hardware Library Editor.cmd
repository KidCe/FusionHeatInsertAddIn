@echo off
setlocal
cd /d "%~dp0"
title Heat Insert Hardware Library Editor

where py >nul 2>nul
if errorlevel 1 goto no_python

py -3 hardware_library_editor_server.py
if errorlevel 1 pause
exit /b

:no_python
echo Python could not be found.
echo Install Python or run hardware_library_editor.html and choose Open Library manually.
pause
