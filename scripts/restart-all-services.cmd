@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-all-services.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo [ERROR] 一键重启失败，退出码 %EXIT_CODE%。
pause
exit /b %EXIT_CODE%
