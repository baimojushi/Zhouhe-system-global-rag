[CmdletBinding()]
param(
  [ValidateSet("user", "project")]
  [string]$Scope = "user",
  [string]$Endpoint = "http://127.0.0.1:9101/mcp",
  [switch]$SkipInstructions
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$uri = [Uri]$Endpoint
if (-not $uri.IsLoopback) {
  throw "拒绝把非回环 MCP 标记为可信：$Endpoint"
}

if ($Scope -eq "user") {
  $qwenRoot = Join-Path $HOME ".qwen"
  $settingsPath = Join-Path $qwenRoot "settings.json"
  $instructionsPath = Join-Path $qwenRoot "QWEN.md"
} else {
  $qwenRoot = Join-Path $RepoRoot ".qwen"
  $settingsPath = Join-Path $qwenRoot "settings.json"
  $instructionsPath = Join-Path $RepoRoot "QWEN.md"
}
New-Item -ItemType Directory -Force -Path $qwenRoot | Out-Null

function Set-JsonProperty([object]$Target, [string]$Name, [object]$Value) {
  if ($Target.PSObject.Properties.Name -contains $Name) {
    $Target.$Name = $Value
  } else {
    $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
  }
}

$settings = [pscustomobject]@{}
if (Test-Path $settingsPath) {
  $timestamp = Get-Date -Format "yyyyMMddHHmmss"
  Copy-Item -LiteralPath $settingsPath -Destination "$settingsPath.backup-$timestamp" -Force
  try {
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    throw "现有 settings.json 不是有效 JSON，已保留原文件和备份，未做修改：$settingsPath"
  }
}

if (-not ($settings.PSObject.Properties.Name -contains "mcp") -or $null -eq $settings.mcp) {
  Set-JsonProperty $settings "mcp" ([pscustomobject]@{})
}
$allowed = @($settings.mcp.allowed | Where-Object { $_ })
if ($allowed -notcontains "global-rag") { $allowed += "global-rag" }
Set-JsonProperty $settings.mcp "allowed" $allowed

if (-not ($settings.PSObject.Properties.Name -contains "mcpServers") -or $null -eq $settings.mcpServers) {
  Set-JsonProperty $settings "mcpServers" ([pscustomobject]@{})
}
$server = [pscustomobject]@{
  httpUrl = $Endpoint
  timeout = 15000
  discoveryTimeoutMs = 10000
  includeTools = @("search_global_knowledge")
  trust = $true
}
Set-JsonProperty $settings.mcpServers "global-rag" $server

$json = $settings | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding $false))

if (-not $SkipInstructions) {
  $template = Join-Path $RepoRoot "config\qwen-code\QWEN.global-rag.md"
  $block = Get-Content -LiteralPath $template -Raw -Encoding UTF8
  $existing = if (Test-Path $instructionsPath) { Get-Content -LiteralPath $instructionsPath -Raw -Encoding UTF8 } else { "" }
  if ($existing -notmatch "GLOBAL-RAG-QWEN-RULES:BEGIN") {
    $combined = if ($existing.Trim()) { $existing.TrimEnd() + "`r`n`r`n" + $block.Trim() + "`r`n" } else { $block.Trim() + "`r`n" }
    [System.IO.File]::WriteAllText($instructionsPath, $combined, (New-Object System.Text.UTF8Encoding $false))
  }
}

Write-Host "[OK] Qwen Code Global RAG 已写入：$settingsPath" -ForegroundColor Green
Write-Host "启动 qwen 后运行 /mcp 和 /mcp schema 验证；该配置不会修改模型提供方，也不会让 Qwen Code 使用本机 GPU。"
