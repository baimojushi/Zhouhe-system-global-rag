[CmdletBinding()]
param(
  [ValidateSet("start", "restart", "stop", "status")]
  [string]$Action = "restart",
  [ValidateSet("q4", "q8", "all")]
  [string]$Profile = "q4",
  [string]$Distro = "Ubuntu-22.04",
  [string]$WslUser = "baimo",
  [string]$LinuxInstallDir = "",
  [int]$ReadyTimeoutSeconds = 480
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($LinuxInstallDir)) {
  $LinuxInstallDir = "/home/$WslUser/.local/share/global-rag-llama"
}
$sourceScript = Join-Path $PSScriptRoot "llama-service.sh"
$linuxScript = "$LinuxInstallDir/llama-service.sh"

function Invoke-Wsl([string]$Command, [switch]$IgnoreExitCode) {
  & wsl.exe -d $Distro -u $WslUser --exec /bin/bash -lc $Command
  $script:LastWslExitCode = $LASTEXITCODE
  if (-not $IgnoreExitCode -and $script:LastWslExitCode -ne 0) {
    throw "WSL 命令失败（$script:LastWslExitCode）：$Command"
  }
}

function Install-Manager {
  if (-not (Test-Path -LiteralPath $sourceScript -PathType Leaf)) {
    throw "源码内缺少 $sourceScript"
  }
  Invoke-Wsl "mkdir -p '$LinuxInstallDir'"
  Get-Content -LiteralPath $sourceScript -Raw | & wsl.exe -d $Distro -u $WslUser --exec /usr/bin/tee $linuxScript | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "复制 llama-service.sh 到 WSL 失败" }
  Invoke-Wsl "chmod 700 '$linuxScript'"
}

function Get-Port([string]$Target) {
  if ($Target -eq "q8") { return 8002 }
  return 8000
}

function Wait-Ready([string]$Target) {
  $port = Get-Port $Target
  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
  do {
    & wsl.exe -d $Distro -u $WslUser --exec /usr/bin/curl -fsS -m 3 "http://127.0.0.1:$port/health" *> $null
    if ($LASTEXITCODE -eq 0) {
      Write-Host "[OK] Gemma $($Target.ToUpper()) 已就绪：$port" -ForegroundColor Green
      return
    }
    Start-Sleep -Seconds 3
  } while ((Get-Date) -lt $deadline)
  $tailArg = "tail -n 100 '/home/$WslUser/.local/state/global-rag-llama/logs/llama_$Target.log'"
  Invoke-Wsl $tailArg -IgnoreExitCode | Out-Null
  throw "Gemma $Target 未在 $ReadyTimeoutSeconds 秒内就绪"
}

Install-Manager

if ($Action -eq "status") {
  & wsl.exe -d $Distro -u $WslUser bash -lc "'$linuxScript' status '$Profile'" *> $null
  $script:LastWslExitCode = $LASTEXITCODE
  exit $script:LastWslExitCode
}

if ($Action -eq "stop" -or $Action -eq "restart") {
  & wsl.exe -d $Distro -u $WslUser bash -lc "'$linuxScript' stop '$Profile'"
  if ($LASTEXITCODE -ne 0) { throw "Gemma stop failed" }
  if ($Action -eq "stop") {
    Write-Host "[OK] Gemma $Profile 已停止" -ForegroundColor Green
    exit 0
  }
}

if ($Profile -eq "all") {
  throw "start/restart 必须明确选择 q4 或 q8；all 只适用于 stop/status。"
}

if ($Action -eq "start") {
  & wsl.exe -d $Distro -u $WslUser bash -lc "'$linuxScript' status '$Profile'" *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Gemma $Profile 已在运行" -ForegroundColor Green
    exit 0
  }
}

$arguments = @("-d", $Distro, "-u", $WslUser, "--exec", "/bin/bash", $linuxScript, "run", $Profile)
Start-Process -FilePath "wsl.exe" -ArgumentList $arguments -WindowStyle Minimized | Out-Null
Wait-Ready $Profile
