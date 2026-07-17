@echo off
cd /d D:\ai\qwen-code\bin\global-rag-system\.next\standalone
xcopy /E /I /Y ..\static _next\static
xcopy /E /I /Y ..\public public
set PORT=3000
node server.js