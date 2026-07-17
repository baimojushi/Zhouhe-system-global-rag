@echo off
setlocal
cd /d "%~dp0.."
set "PORT=3000"
set "UI_HOSTNAME=127.0.0.1"
node scripts\start-local.mjs
exit /b %errorlevel%
