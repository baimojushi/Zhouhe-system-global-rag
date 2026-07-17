@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage-gemma.ps1" -Action restart -Profile q8
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
