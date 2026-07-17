@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "PYTHONUTF8=1"
set "LLAMA_WSL_DISTRO=Ubuntu-22.04"
set "LLAMA_WSL_USER=baimo"

set "PYTHON_EXE=D:\ai\qwen_deploy\.conda\python.exe"
set "CHAT_SCRIPT=%SCRIPT_DIR%llama_chat_persistent_v3.py"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python 不存在：
    echo   %PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%CHAT_SCRIPT%" (
    echo [ERROR] 交互脚本不存在：
    echo   %CHAT_SCRIPT%
    pause
    exit /b 1
)

echo 检查 WSL 内部与 Windows 端口...
for %%P in (8000 8001 8002) do (
    set "WSL_OK="
    set "WIN_OK="

    wsl.exe -d Ubuntu-22.04 -u baimo --exec /usr/bin/curl -fsS -m 3 ^
      http://127.0.0.1:%%P/health >nul 2>&1
    if not errorlevel 1 set "WSL_OK=1"

    curl.exe --noproxy "*" -fsS -m 3 ^
      http://127.0.0.1:%%P/health >nul 2>&1
    if not errorlevel 1 set "WIN_OK=1"

    if defined WSL_OK (
        if defined WIN_OK (
            echo   [OK] %%P: WSL + Windows localhost
        ) else (
            echo   [WARN] %%P: WSL 内健康，Windows localhost 不通
        )
    ) else (
        echo   [--] %%P: WSL 内无服务
    )
)
echo.

"%PYTHON_EXE%" "%CHAT_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo 交互脚本退出代码：%EXIT_CODE%
pause
exit /b %EXIT_CODE%
