@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-all-services.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo [ERROR] 停止服务未完全成功，退出码 %EXIT_CODE%。
pause
exit /b %EXIT_CODE%
