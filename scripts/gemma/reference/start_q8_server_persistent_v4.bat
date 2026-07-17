@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "DISTRO=Ubuntu-22.04"
set "WSL_USER=baimo"
set "SERVICE_NAME=llama_q8"
set "SERVICE_PORT=8002"
set "SOURCE_SH=%~dp0q8-server-persistent.sh"
set "LINUX_DIR=/home/baimo/.local/share/llama-start"
set "LINUX_SH=/home/baimo/.local/share/llama-start/q8-server-persistent.sh"
set "LOG_FILE=/home/baimo/q8-server.log"
set "MAX_ATTEMPTS=140"

echo ========================================
echo  Gemma 4 31B Q8_0 persistent server
echo  端口: %SERVICE_PORT%
echo  持久化方式: 独立 wsl.exe 宿主进程
echo ========================================
echo.

if not exist "%SOURCE_SH%" (
    echo [ERROR] 缺少启动脚本:
    echo   %SOURCE_SH%
    pause
    exit /b 1
)

echo [1/6] 启动并检查 WSL...
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/true >nul 2>&1
if errorlevel 1 (
    echo [ERROR] WSL 发行版或用户不可用: %DISTRO% / %WSL_USER%
    pause
    exit /b 1
)
echo    WSL 正常

echo [2/6] 停止旧 llama-server...
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/pkill -TERM -f /home/llama.cpp/build/bin/llama-server >nul 2>&1
timeout /t 2 >nul 2>&1
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/pkill -KILL -f /home/llama.cpp/build/bin/llama-server >nul 2>&1
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/rm -f ^
  /home/%WSL_USER%/.local/state/llama/llama_q4.wrapper.pid ^
  /home/%WSL_USER%/.local/state/llama/llama_q4.server.pid ^
  /home/%WSL_USER%/.local/state/llama/llama_q8.wrapper.pid ^
  /home/%WSL_USER%/.local/state/llama/llama_q8.server.pid >nul 2>&1
echo    旧进程已清理

echo [3/6] 检查模型文件...
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/test -s /home/baimo/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00001-of-00009.gguf >nul 2>&1
if errorlevel 1 goto MODEL_MISSING
wsl.exe -d Ubuntu-22.04 -u baimo --exec /usr/bin/test -s /home/baimo/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00009-of-00009.gguf >nul 2>&1
if errorlevel 1 goto MODEL_MISSING
echo    模型检查通过

echo [4/6] 安装 Linux 启动脚本...
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/mkdir -p %LINUX_DIR% >nul 2>&1
if errorlevel 1 goto COPY_FAILED

REM 通过标准输入复制，避免 Windows 路径、空格和 /mnt/f 映射问题
type "%SOURCE_SH%" | wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/tee %LINUX_SH% >nul
if errorlevel 1 goto COPY_FAILED

wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/chmod 700 %LINUX_SH% >nul 2>&1
if errorlevel 1 goto COPY_FAILED
echo    已安装到 %LINUX_SH%

echo [5/6] 启动独立 WSL 宿主进程...

REM 清空旧日志，防止启动器失败时显示上一次运行内容
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/rm -f /home/baimo/q8-server.log >nul 2>&1

REM start 的第一个参数是窗口标题；后续直接调用 wsl.exe。
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Windows PATH 中找不到 wsl.exe
    goto START_FAILED
)

start "%SERVICE_NAME%_host" /min wsl.exe ^
  -d %DISTRO% -u %WSL_USER% --exec /bin/bash %LINUX_SH%
if errorlevel 1 goto START_FAILED

REM 给独立 wsl.exe 一点时间创建 wrapper/server PID 文件
timeout /t 2 >nul 2>&1
echo    已提交启动请求

echo [6/6] 等待服务就绪...
set /a ATTEMPTS=0

:WAIT_LOOP
timeout /t 3 >nul 2>&1
set /a ATTEMPTS+=1

wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/curl -fsS -m 3 ^
  http://127.0.0.1:%SERVICE_PORT%/health >nul 2>&1
if not errorlevel 1 goto STABILITY_CHECK

REM PID 文件和进程需同时有效；服务仍在加载时 PID 文件必须持续存在。
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/test -s /home/%WSL_USER%/.local/state/llama/%SERVICE_NAME%.server.pid >nul 2>&1
if errorlevel 1 (
    if !ATTEMPTS! leq 10 (
        echo    等待宿主进程创建 PID 文件... (!ATTEMPTS!/10)
        goto WAIT_LOOP
    )
    goto START_FAILED
)

wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/pgrep -f /home/llama.cpp/build/bin/llama-server >nul 2>&1
if errorlevel 1 goto START_FAILED

if !ATTEMPTS! geq %MAX_ATTEMPTS% goto START_TIMEOUT
echo    仍在加载... (!ATTEMPTS!/%MAX_ATTEMPTS%)
goto WAIT_LOOP

:STABILITY_CHECK
echo    服务首次就绪，进行 15 秒稳定性检查...
set /a STABLE=0

:STABLE_LOOP
timeout /t 3 >nul 2>&1
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/curl -fsS -m 3 http://127.0.0.1:%SERVICE_PORT%/health >nul 2>&1
if errorlevel 1 (
    echo    健康检查暂时不可用，返回加载等待...
    goto WAIT_LOOP
)
set /a STABLE+=1
if !STABLE! lss 5 goto STABLE_LOOP

goto SERVICE_READY

:SERVICE_READY
set "WINDOWS_API="

curl.exe --noproxy "*" -fsS -m 3 ^
  http://127.0.0.1:%SERVICE_PORT%/health >nul 2>&1
if not errorlevel 1 (
    set "WINDOWS_API=http://127.0.0.1:%SERVICE_PORT%/v1"
)

set "WSL_IP="
for /f "tokens=1" %%I in ('wsl.exe -d %DISTRO% --exec hostname -I 2^>nul') do (
    if not defined WSL_IP set "WSL_IP=%%I"
)

if not defined WINDOWS_API if defined WSL_IP (
    curl.exe --noproxy "*" -fsS -m 3 ^
      http://!WSL_IP!:%SERVICE_PORT%/health >nul 2>&1
    if not errorlevel 1 (
        set "WINDOWS_API=http://!WSL_IP!:%SERVICE_PORT%/v1"
    )
)

echo.
echo ========================================
echo  [OK] %SERVICE_NAME% 已稳定运行
if defined WINDOWS_API (
    echo  Windows API: !WINDOWS_API!
) else (
    echo  [WARN] WSL 内服务健康，Windows 网络当前不可达
    echo  WSL IPv4: !WSL_IP!
)
echo  WSL API: http://127.0.0.1:%SERVICE_PORT%/v1
echo  日志: %LOG_FILE%
echo  宿主: 独立最小化 wsl.exe 窗口，请勿结束该进程
echo ========================================
pause
exit /b 0

:MODEL_MISSING
echo [ERROR] 模型文件不存在或为空。
echo   /home/baimo/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00001-of-00009.gguf
if not "/home/baimo/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00009-of-00009.gguf"=="" echo   /home/baimo/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00009-of-00009.gguf
pause
exit /b 1

:COPY_FAILED
echo [ERROR] Linux 启动脚本复制或授权失败。
pause
exit /b 1

:START_TIMEOUT
echo [ERROR] 服务加载超时。
goto SHOW_LOG

:START_FAILED
echo [ERROR] 服务进程提前退出或稳定性检查失败。

:SHOW_LOG
echo.
echo ---------- 日志末尾 ----------
wsl.exe -d %DISTRO% -u %WSL_USER% --exec /usr/bin/tail -n 80 %LOG_FILE%
echo ------------------------------
pause
exit /b 1
