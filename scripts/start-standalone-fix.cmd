@echo off
rem Standalone startup helper — copies static assets then calls start-local.mjs
setlocal
cd /d "%~dp0.."
rem Copy .next/static into standalone (Next.js standalone needs these at .next/static)
xcopy /E /I /Y ".next\static" ".next\standalone\.next\static" >nul 2>&1
rem Copy public assets
xcopy /E /I /Y "public" ".next\standalone\public" >nul 2>&1
rem Use the same entry point as npm start
set "PORT=3000"
set "UI_HOSTNAME=127.0.0.1"
node scripts\start-local.mjs
exit /b %errorlevel%
