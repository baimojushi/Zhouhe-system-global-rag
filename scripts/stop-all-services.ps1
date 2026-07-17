[CmdletBinding()]
param(
  [string]$Distro = "Ubuntu-22.04",
  [string]$WslUser = "baimo",
  [string]$LinuxRoot = "/opt/global-rag",
  [int]$GatewayPort = 9100,
  [int]$UiPort = 3000,
  [switch]$KeepWeaviate
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $RepoRoot ".runtime"

function Invoke-Wsl([string]$Command, [switch]$IgnoreExitCode) {
  & wsl.exe -d $Distro -u $WslUser --exec /bin/bash -lc $Command
  if (-not $IgnoreExitCode -and $LASTEXITCODE -ne 0) {
    throw "WSL 命令失败（$LASTEXITCODE）：$Command"
  }
}

Write-Host "[1/5] 停止 Web GUI..." -ForegroundColor Cyan
$localCompose = Join-Path $RepoRoot "docker-compose.local.yml"
if ((Get-Command docker.exe -ErrorAction SilentlyContinue) -and (Test-Path $localCompose)) {
  & docker.exe compose -f $localCompose stop rag-gui sky-updater *> $null
}
$uiPidFile = Join-Path $RuntimeDir "ui.pid"
if (Test-Path $uiPidFile) {
  $uiPid = [int](Get-Content $uiPidFile -Raw)
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $uiPid" -ErrorAction SilentlyContinue
  if ($process -and $process.CommandLine -match "start-local\.mjs") {
    Stop-Process -Id $uiPid -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $uiPidFile -Force -ErrorAction SilentlyContinue
}
$listeners = Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
  if ($process -and ($process.CommandLine -match "start-local\.mjs" -or $process.CommandLine -like "*$RepoRoot*")) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
  } elseif ($process) {
    Write-Warning "端口 $UiPort 由非本项目进程占用（PID $($listener.OwningProcess)），未停止。"
  }
}

Write-Host "[2/5] 停止 RAG Gateway..." -ForegroundColor Cyan
$gatewayStopScript = @'
if [ -s /opt/global-rag/run/gateway.pid ]; then
  pid=$(cat /opt/global-rag/run/gateway.pid)
  if [ -r /proc/$pid/cmdline ] && tr '\0' ' ' < /proc/$pid/cmdline | grep -q rag_gateway.py; then
    kill -TERM $pid 2>/dev/null || true
  fi
fi
sleep 1
pkill -TERM -f '[r]ag_gateway.py' 2>/dev/null || true
rm -f /opt/global-rag/run/gateway.pid
'@
# Use wsl.exe with pipe to deliver bash script via stdin (PS 5.1 doesn't support <<<)
$gatewayStopScript | & wsl.exe -d $Distro -u $WslUser bash -s

Write-Host "[3/5] 停止 Gemma Q4/Q8..." -ForegroundColor Cyan
$gemmaManager = Join-Path $PSScriptRoot "gemma\manage-gemma.ps1"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $gemmaManager -Action stop -Profile all -Distro $Distro -WslUser $WslUser
if ($LASTEXITCODE -ne 0) { throw "Gemma 服务停止失败" }

Write-Host "[4/5] 处理 Weaviate..." -ForegroundColor Cyan
if ($KeepWeaviate) {
  Write-Host "按参数保留 Weaviate 运行。"
} else {
  Invoke-Wsl "cd '$LinuxRoot/stack' && docker compose stop weaviate"
}

Write-Host "[5/5] 清理本项目运行记录..." -ForegroundColor Cyan
if (Test-Path $RuntimeDir) {
  Get-ChildItem -LiteralPath $RuntimeDir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}
Write-Host "[OK] 本项目服务已停止。未调用 wsl --shutdown，也未终止无关端口进程。" -ForegroundColor Green
