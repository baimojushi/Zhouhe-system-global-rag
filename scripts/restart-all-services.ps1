[CmdletBinding()]
param(
  [string]$Distro = "Ubuntu-22.04",
  [string]$WslUser = "baimo",
  [string]$LinuxRoot = "/opt/global-rag",
  [ValidateSet("q4", "q8")]
  [string]$GemmaProfile = "q4",
  [int]$GemmaPort = 0,
  [int]$GatewayPort = 9100,
  [int]$UiPort = 3000,
  [switch]$Build
)

$ErrorActionPreference = "Stop"
if ($GemmaPort -eq 0) { $GemmaPort = $(if ($GemmaProfile -eq "q8") { 8002 } else { 8000 }) }
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $RepoRoot ".runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$WindowsRagRoot = "E:\RAG"
$WindowsRagFolders = @("AI工作记录", "学术资料", "生产文档", "个人思维笔记")
New-Item -ItemType Directory -Force -Path $WindowsRagRoot | Out-Null
foreach ($folder in $WindowsRagFolders) {
  New-Item -ItemType Directory -Force -Path (Join-Path $WindowsRagRoot $folder) | Out-Null
}
Write-Host "[OK] 原始资料目录 $WindowsRagRoot 已准备（关联知识库不创建文件夹）" -ForegroundColor Green

# Read .env file (for reference; Weaviate auth is handled inside WSL scripts)
$envFile = Join-Path $LinuxRoot "stack/.env"
if (Test-Path $envFile) {
    Write-Host "[OK] .env 文件存在: $envFile" -ForegroundColor Green
}

function Test-Http([string]$Url, [int]$TimeoutSeconds = 3) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSeconds
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
  } catch { return $false }
}

function Wait-Http([string]$Name, [string]$Url, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    if (Test-Http $Url) { Write-Host "[OK] $Name $Url" -ForegroundColor Green; return }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  throw "$Name 未在 $TimeoutSeconds 秒内就绪：$Url"
}

function Wait-Tcp([string]$Name, [int]$Port, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
      $task = $client.ConnectAsync("127.0.0.1", $Port)
      if ($task.Wait(1500) -and $client.Connected) {
        Write-Host "[OK] $Name 127.0.0.1:$Port" -ForegroundColor Green; return
      }
    } catch { } finally { $client.Dispose() }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  throw "$Name 端口 $Port 未在 $TimeoutSeconds 秒内就绪"
}

function Invoke-Wsl([string]$Command, [switch]$IgnoreExitCode) {
  & wsl.exe -d $Distro -u $WslUser --exec /bin/bash -lc $Command
  if (-not $IgnoreExitCode -and $LASTEXITCODE -ne 0) { throw "WSL 命令失败（$LASTEXITCODE）：$Command" }
}

function Wait-Wsl([string]$Name, [string]$Command, [int]$TimeoutSeconds) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    & wsl.exe -d $Distro -u $WslUser --exec /bin/bash -lc $Command *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] $Name" -ForegroundColor Green; return }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  throw "$Name 未在 $TimeoutSeconds 秒内就绪"
}

# ── Write a shell script to WSL without BOM/CRLF ─────
function Write-WslScript([string]$LinuxPath, [string]$Content) {
  # Strip BOM from raw bytes, convert CRLF→LF
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Content)
  $start = 0
  if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    $start = 3
  }
  $text = [System.Text.Encoding]::UTF8.GetString($bytes, $start, $bytes.Length - $start)
  $text = $text -replace "`r`n", "`n"
  # Write to a temp Windows file, then cp into WSL to avoid PowerShell pipe encoding
  $tmpWin = Join-Path $env:TEMP "wsl-script-$([guid]::NewGuid().ToString('N').Substring(0,8)).sh"
  [System.IO.File]::WriteAllText($tmpWin, $text, (New-Object System.Text.UTF8Encoding $false))
  # Convert Windows path to WSL mount path: C:\foo\bar → /mnt/c/foo/bar
  $driveLetter = $tmpWin[0].ToString().ToLower()
  $restPath = $tmpWin.Substring(2).Replace('\', '/')
  $wslTmpPath = "/mnt/$driveLetter$restPath"
  & wsl.exe -d $Distro -u $WslUser bash -c "cp '$wslTmpPath' '$LinuxPath' && chmod +x '$LinuxPath'"
  Remove-Item $tmpWin -Force -ErrorAction SilentlyContinue
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1/5] Weaviate
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write-Host "[1/5] 启动 Weaviate..." -ForegroundColor Cyan
$stackRoot = "$LinuxRoot/stack"
Invoke-Wsl "cd '$stackRoot' && docker compose up -d weaviate"
Wait-Tcp "Weaviate HTTP" 8080 90
Wait-Tcp "Weaviate gRPC" 50051 30
Wait-Tcp "Weaviate metrics" 2112 30

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2/5] Gemma (llama.cpp)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write-Host "[2/5] 重启 llama.cpp Gemma $($GemmaProfile.ToUpper())..." -ForegroundColor Cyan
$gemmaManager = Join-Path $PSScriptRoot "gemma\manage-gemma.ps1"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $gemmaManager -Action restart -Profile $GemmaProfile -Distro $Distro -WslUser $WslUser
if ($LASTEXITCODE -ne 0) {
  Write-Host "[WARN] Gemma $GemmaProfile 启动异常（退出码 $LASTEXITCODE），继续其他服务" -ForegroundColor Yellow
} else {
  Wait-Tcp "Gemma $($GemmaProfile.ToUpper())" $GemmaPort 30
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3/5] RAG Gateway + Ingest Worker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write-Host "[3/5] 重启 RAG Gateway（内置 BGE-M3）..." -ForegroundColor Cyan
$gatewayScript = @'
#!/usr/bin/env bash
set -Eeuo pipefail
mkdir -p /opt/global-rag/run /opt/global-rag/logs
export RAG_INGEST_ROOTS=/mnt/e/RAG
mkdir -p "/mnt/e/RAG/AI工作记录" "/mnt/e/RAG/学术资料" "/mnt/e/RAG/生产文档" "/mnt/e/RAG/个人思维笔记"
if [ -s /opt/global-rag/run/gateway.pid ]; then
  oldpid=$(cat /opt/global-rag/run/gateway.pid)
  if [ -r /proc/$oldpid/cmdline ] && tr '\0' ' ' < /proc/$oldpid/cmdline | grep -q rag_gateway.py; then
    kill $oldpid 2>/dev/null || true
  fi
fi
pkill -TERM -f '[r]ag_gateway.py' 2>/dev/null || true
if [ -s /opt/global-rag/run/ingest-worker.pid ]; then
  worker_pid=$(cat /opt/global-rag/run/ingest-worker.pid)
  if [ -r /proc/$worker_pid/cmdline ] && tr '\0' ' ' < /proc/$worker_pid/cmdline | grep -q ingest_worker.py; then
    kill $worker_pid 2>/dev/null || true
  fi
fi
pkill -TERM -f '[i]ngest_worker.py' 2>/dev/null || true
if [ -s /opt/global-rag/run/rag-mcp.pid ]; then
  mcp_pid=$(cat /opt/global-rag/run/rag-mcp.pid)
  if [ -r /proc/$mcp_pid/cmdline ] && tr '\0' ' ' < /proc/$mcp_pid/cmdline | grep -q rag_mcp_server.py; then
    kill $mcp_pid 2>/dev/null || true
  fi
fi
pkill -TERM -f '[r]ag_mcp_server.py' 2>/dev/null || true
if [ -s /opt/global-rag/run/embedding-service.pid ]; then
  embed_pid=$(cat /opt/global-rag/run/embedding-service.pid)
  if [ -r /proc/$embed_pid/cmdline ] && tr '\0' ' ' < /proc/$embed_pid/cmdline | grep -q embedding_service.py; then
    kill $embed_pid 2>/dev/null || true
  fi
fi
pkill -TERM -f '[e]mbedding_service.py' 2>/dev/null || true
sleep 2
cd /opt/global-rag
nohup /opt/global-rag/venv/bin/python3 /opt/global-rag/embedding_service.py >> /opt/global-rag/logs/embedding-service.log 2>&1 &
echo $! > /opt/global-rag/run/embedding-service.pid
nohup env RAG_INGEST_ROOTS=/mnt/e/RAG RAG_AUTO_SCAN_SECONDS=300 RAG_FILE_STABILITY_SECONDS=30 /opt/global-rag/venv/bin/python3 /opt/global-rag/ingest_worker.py >> /opt/global-rag/logs/ingest_worker.log 2>&1 &
echo $! > /opt/global-rag/run/ingest-worker.pid
nohup /opt/global-rag/venv/bin/python3 /opt/global-rag/rag_gateway.py --port 9100 >> /opt/global-rag/logs/gateway.log 2>&1 &
echo $! > /opt/global-rag/run/gateway.pid
nohup env RAG_GATEWAY_URL=http://127.0.0.1:9100 RAG_MCP_HOST=127.0.0.1 RAG_MCP_PORT=9101 /opt/global-rag/venv/bin/python3 /opt/global-rag/rag_mcp_server.py >> /opt/global-rag/logs/rag-mcp.log 2>&1 &
echo $! > /opt/global-rag/run/rag-mcp.pid
'@
$ts = Get-Date -Format "yyyyMMddHHmmss"
$tmpGatewayScript = "/tmp/rag-start-gateway-${ts}.sh"
Write-WslScript $tmpGatewayScript $gatewayScript
& wsl.exe -d $Distro -u $WslUser bash -c "$tmpGatewayScript && rm -f '$tmpGatewayScript'"
Wait-Http "Embedding Service" "http://127.0.0.1:9102/health" 240
Wait-Http "RAG Gateway" "http://127.0.0.1:$GatewayPort/health" 240
Wait-Tcp "Global RAG MCP" 9101 30
Wait-Wsl "摄取 Worker" "test -s /opt/global-rag/run/ingest-worker.pid && kill -0 `$(cat /opt/global-rag/run/ingest-worker.pid)" 30
Wait-Wsl "Global RAG MCP 进程" "test -s /opt/global-rag/run/rag-mcp.pid && kill -0 `$(cat /opt/global-rag/run/rag-mcp.pid)" 30

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4/5] Web GUI (Windows Node.js)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write-Host "[4/5] 重启 Web GUI..." -ForegroundColor Cyan
$uiPidFile = Join-Path $RuntimeDir "ui.pid"
if (Test-Path $uiPidFile) {
  $oldUiPid = [int](Get-Content $uiPidFile -Raw)
  $ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $oldUiPid" -ErrorAction SilentlyContinue
  if ($ownedProcess -and $ownedProcess.CommandLine -match "start-local\.mjs") {
    Stop-Process -Id $oldUiPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }
  Remove-Item $uiPidFile -Force -ErrorAction SilentlyContinue
}

$listeners = Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
  $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
  if ($listenerProcess -and ($listenerProcess.CommandLine -match "start-local\.mjs" -or $listenerProcess.CommandLine -like "*$RepoRoot*")) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
  } else {
    throw "端口 $UiPort 已被非本项目进程占用（PID $($listener.OwningProcess)），为避免误杀已停止。"
  }
}

Push-Location $RepoRoot
try {
  $standaloneServer = Join-Path ".next" "standalone/server.js"
  if ($Build -or -not (Test-Path $standaloneServer)) {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Web GUI 构建失败" }
  }
  $stdout = Join-Path $RuntimeDir "ui.stdout.log"
  $stderr = Join-Path $RuntimeDir "ui.stderr.log"
  $ui = Start-Process -FilePath "node.exe" -ArgumentList "scripts/start-local.mjs" -WorkingDirectory $RepoRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
  Set-Content -Path $uiPidFile -Value $ui.Id -Encoding ascii
} finally { Pop-Location }
Wait-Http "Web GUI" "http://127.0.0.1:$UiPort" 90

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [5/5] 前端静态资源验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write-Host "[5/5] 验证前端静态资源..." -ForegroundColor Cyan
Push-Location $RepoRoot
try {
  & npm.cmd run verify:ui
  if ($LASTEXITCODE -ne 0) { throw "前端 JS/CSS 静态资源验证失败" }
} finally { Pop-Location }

Write-Host ""
Write-Host "全部服务已就绪" -ForegroundColor Green
Write-Host "  GUI       http://127.0.0.1:$UiPort"
Write-Host "  Gateway   http://127.0.0.1:$GatewayPort/health"
Write-Host "  原始资料  E:\RAG"
Write-Host "  Gemma     http://127.0.0.1:$GemmaPort/health"
Write-Host "  Weaviate  http://127.0.0.1:8080/v1/.well-known/ready"
