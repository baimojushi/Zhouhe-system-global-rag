import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { join, resolve } from "node:path";

/**
 * POST /api/services/restart
 *
 * Body: { service: "all" | "weaviate" | "gateway" | "gemma" | "ui", profile?: "q4" | "q8" }
 * Kills the old process, then starts the service again.
 */
export const dynamic = "force-dynamic";

// Resolve repo root relative to this file's location
// In Next.js standalone: __dirname points to .next/server/app/api/services/restart
const apiDir = __dirname;
const repoRoot = resolve(apiDir, "../../../../");

function spawnPsCommand(
  command: string,
  cwd: string,
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], {
      cwd,
      shell: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    child.on("close", (code) => {
      resolve({
        ok: code === 0,
        stdout: Buffer.concat(stdout).toString("utf-8"),
        stderr: Buffer.concat(stderr).toString("utf-8"),
      });
    });
    child.on("error", () => {
      resolve({ ok: false, stdout: "", stderr: "spawn error" });
    });
  });
}

export async function POST(request: NextRequest) {
  let body: { service: string; profile?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "无效的请求体" }, { status: 400 });
  }

  const { service, profile } = body;
  if (!service || !["all", "weaviate", "gateway", "gemma", "ui"].includes(service)) {
    return NextResponse.json({ error: "不支持的服务: " + service }, { status: 400 });
  }

  // All
  if (service === "all") {
    const ps1Path = join(repoRoot, "scripts", "restart-all-services.ps1");
    const result = await spawnPsCommand(`& "${ps1Path}"`, repoRoot);
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "全部服务重启中，请稍候" : "重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // Weaviate — docker compose in repo's backend/stack
  if (service === "weaviate") {
    const stackDir = join(repoRoot, "backend", "stack");
    await spawnPsCommand(`cd "${stackDir}" 2>$null; docker compose stop weaviate 2>$null; docker compose rm -f weaviate 2>$null`, repoRoot);
    const result = await spawnPsCommand(`cd "${stackDir}" 2>$null; docker compose up -d weaviate`, repoRoot);
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "Weaviate 正在重启" : "Weaviate 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // Gateway — kill + nohup via WSL
  if (service === "gateway") {
    const result = await spawnPsCommand(
      'wsl.exe -d Ubuntu-22.04 -u baimo --exec /bin/bash -lc "pkill -TERM -f \'[r]ag_gateway.py\' 2>/dev/null; sleep 2; cd /opt/global-rag && nohup /opt/global-rag/venv/bin/python3 /opt/global-rag/rag_gateway.py --port 9100 >> /opt/global-rag/logs/gateway.log 2>&1 & echo $!"',
      repoRoot,
    );
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "RAG Gateway 正在重启" : "Gateway 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // Gemma — manage-gemma.ps1
  if (service === "gemma") {
    const p = profile || "q4";
    const ps1Path = join(repoRoot, "scripts", "gemma", "manage-gemma.ps1");
    const result = await spawnPsCommand(`& "${ps1Path}" -Action restart -Profile ${p}`, repoRoot);
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? `Gemma ${p.toUpperCase()} 正在重启` : "Gemma 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // UI — kill old node, then start
  if (service === "ui") {
    await spawnPsCommand(
      `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'start-local\\.mjs' -and $_.CommandLine -match 'global-rag-system' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } 2>$null`,
      repoRoot,
    );
    const mjsPath = join(repoRoot, "scripts", "start-local.mjs");
    const result = await spawnPsCommand(`& "${mjsPath}"`, repoRoot);
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "Web GUI 正在重启" : "GUI 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  return NextResponse.json({ error: "未知服务" }, { status: 500 });
}