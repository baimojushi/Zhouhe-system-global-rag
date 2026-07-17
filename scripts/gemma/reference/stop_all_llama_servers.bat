@echo off
chcp 65001 >nul
setlocal

echo ========================================
echo  停止所有 llama-server 服务
echo ========================================
echo.

echo 终止所有 llama-server / llama-bench 进程 (WSL)...
set "SCRIPT_DIR=%~dp0"
wsl -d Ubuntu-22.04 bash -c "bash /mnt/f/scripts/Gemma/stop_llama_wsl.sh"

echo.
echo 清理端口 8000/8001/8002 占用...
powershell -NoProfile -Command ^
  "$pids = @(); foreach ($line in (netstat -ano ^| Select-String 'LISTENING')) { if ($line.Line -match ':\s*(8000|8001|8002)\s+.*\s+(\d+)$') { $pids += $Matches[2] } }; foreach ($pid in $pids) { try { taskkill /f /pid $pid | Out-Null } catch {} }" 2>nul

echo.
echo [OK] 清理完成
echo    如需完全释放显存，可运行:
echo      wsl --shutdown
pause