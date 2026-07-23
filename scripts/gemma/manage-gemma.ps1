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

function Invoke-WslBash([string]$Command, [switch]$IgnoreExitCode) {
  & wsl.exe -d $Distro -u $WslUser bash -lc $Command
  $script:LastWslExitCode = $LASTEXITCODE
  if (-not $IgnoreExitCode -and $script:LastWslExitCode -ne 0) {
    throw "WSL bash 命令失败（$script:LastWslExitCode）：$Command"
  }
}

function Install-Manager {
  if (-not (Test-Path -LiteralPath $sourceScript -PathType Leaf)) {
    throw "源码内缺少 $sourceScript"
  }
  Invoke-Wsl "mkdir -p '$LinuxInstallDir'"

  # Read raw bytes to avoid PowerShell BOM injection
  $rawBytes = [System.IO.File]::ReadAllBytes($sourceScript)
  # Strip UTF-8 BOM if present (EF BB BF)
  $startOffset = 0
  if ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF) {
    $startOffset = 3
  }
  $content = [System.Text.Encoding]::UTF8.GetString($rawBytes, $startOffset, $rawBytes.Length - $startOffset)
  # Convert CRLF to LF
  $content = $content -replace "`r`n", "`n"

  # Write to a temp Windows file, then cp into WSL to avoid PowerShell pipe encoding
  $tmpWin = Join-Path $env:TEMP "wsl-llama-service-$([guid]::NewGuid().ToString('N').Substring(0,8)).sh"
  [System.IO.File]::WriteAllText($tmpWin, $content, (New-Object System.Text.UTF8Encoding $false))
  # Convert Windows path to WSL mount path: C:\foo\bar → /mnt/c/foo/bar
  $driveLetter = $tmpWin[0].ToString().ToLower()
  $restPath = $tmpWin.Substring(2).Replace('\', '/')
  $wslTmpPath = "/mnt/$driveLetter$restPath"
  & wsl.exe -d $Distro -u $WslUser bash -c "cp '$wslTmpPath' '$linuxScript' && chmod 700 '$linuxScript'"
  Remove-Item $tmpWin -Force -ErrorAction SilentlyContinue

  # Verify
  $fileCheck = & wsl.exe -d $Distro -u $WslUser bash -c "file '$linuxScript'" 2>&1
  if ($fileCheck -match "CRLF" -or $fileCheck -match "BOM") {
    Write-Host "[WARN] llama-service.sh 仍有编码问题，尝试 sed 修复..." -ForegroundColor Yellow
    & wsl.exe -d $Distro -u $WslUser bash -c "sed -i '1s/^\xef\xbb\xbf//' '$linuxScript' && sed -i 's/\r$//' '$linuxScript'"
    $fileCheck2 = & wsl.exe -d $Distro -u $WslUser bash -c "file '$linuxScript'" 2>&1
    if ($fileCheck2 -match "CRLF" -or $fileCheck2 -match "BOM") {
      throw "llama-service.sh 编码修复失败：$fileCheck2"
    }
  }
}

function Get-Port([string]$Target) {
  if ($Target -eq "q8") { return 8002 }
  return 8000
}

function Wait-Ready([string]$Target) {
  $port = Get-Port $Target
  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
  do {
    try {
      $tcp = [System.Net.Sockets.TcpClient]::new()
      $task = $tcp.ConnectAsync("127.0.0.1", $port)
      if ($task.Wait(2000) -and $tcp.Connected) {
        $tcp.Dispose()
        Write-Host "[OK] Gemma $($Target.ToUpper()) 已就绪：$port" -ForegroundColor Green
        return
      }
      $tcp.Dispose()
    } catch { }
    Start-Sleep -Seconds 3
  } while ((Get-Date) -lt $deadline)
  # Dump log tail on failure
  & wsl.exe -d $Distro -u $WslUser bash -c "tail -n 80 '/home/$WslUser/.local/state/global-rag-llama/logs/llama_$Target.log'" 2>$null
  throw "Gemma $Target 未在 $ReadyTimeoutSeconds 秒内就绪"
}

# ── Main ──────────────────────────────────────────────
Install-Manager

if ($Action -eq "status") {
  & wsl.exe -d $Distro -u $WslUser bash -c "$linuxScript status '$Profile'" *> $null
  exit $LASTEXITCODE
}

if ($Action -eq "stop" -or $Action -eq "restart") {
  # Stop must not throw — it's normal for stop to fail if nothing is running
  & wsl.exe -d $Distro -u $WslUser bash -c "$linuxScript stop '$Profile'" *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Gemma $Profile stop 返回非零（可能未在运行），继续..." -ForegroundColor Yellow
  }
  if ($Action -eq "stop") {
    Write-Host "[OK] Gemma $Profile 已停止" -ForegroundColor Green
    exit 0
  }
}

if ($Profile -eq "all") {
  throw "start/restart 必须明确选择 q4 或 q8；all 只适用于 stop/status。"
}

if ($Action -eq "start") {
  & wsl.exe -d $Distro -u $WslUser bash -c "$linuxScript status '$Profile'" *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Gemma $Profile 已在运行" -ForegroundColor Green
    exit 0
  }
}

# Start via independent wsl.exe window (same as start_q4_server_persistent_v4.bat)
$arguments = @("-d", $Distro, "-u", $WslUser, "--exec", "/bin/bash", $linuxScript, "run", $Profile)
Start-Process -FilePath "wsl.exe" -ArgumentList $arguments -WindowStyle Minimized | Out-Null
Wait-Ready $Profile
