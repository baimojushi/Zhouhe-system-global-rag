import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";

/**
 * POST /api/services/restart
 *
 * Body: { service: "all" | "weaviate" | "gateway" | "gemma" | "ui" }
 */
export const dynamic = "force-dynamic";

function runWsl(command: string): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn("wsl.exe", ["-d", "Ubuntu-22.04", "-u", "baimo", "--", "/bin/bash", "-c", command], {
      shell: false,
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

function runPs(command: string): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], {
      shell: false,
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

  // Gateway — kill + restart via tmux
  if (service === "gateway") {
    await runWsl("tmux kill-session -t rag-gateway 2>/dev/null; sleep 1");
    const result = await runWsl(
      "tmux new-session -d -s rag-gateway 'cd /opt/global-rag && source venv/bin/activate && python3 rag_gateway.py --port 9100 --host 0.0.0.0'"
    );
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "RAG Gateway 正在重启" : "Gateway 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // Weaviate — docker compose restart
  if (service === "weaviate") {
    await runWsl("cd /opt/global-rag/stack && docker compose stop weaviate 2>/dev/null");
    const result = await runWsl("cd /opt/global-rag/stack && docker compose up -d weaviate");
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "Weaviate 正在重启" : "Weaviate 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // Gemma — kill + restart via manage-gemma.ps1
  if (service === "gemma") {
    const p = profile || "q4";
    const result = await runPs(
      `& "D:\\ai\\qwen-code\\bin\\global-rag-system\\scripts\\gemma\\manage-gemma.ps1" -Action restart -Profile ${p}`
    );
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? `Gemma ${p.toUpperCase()} 正在重启` : "Gemma 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // UI — kill old node, then start
  if (service === "ui") {
    await runPs(
      "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'start-local\\.mjs' -and $_.CommandLine -match 'global-rag-system' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } 2>$null"
    );
    const mjsPath = "D:\\ai\\qwen-code\\bin\\global-rag-system\\scripts\\start-local.mjs";
    const result = await runPs(`& node "${mjsPath}"`);
    return NextResponse.json({
      ok: result.ok,
      message: result.ok ? "Web GUI 正在重启" : "GUI 重启失败: " + result.stderr.slice(0, 200),
    });
  }

  // All
  if (service === "all") {
    // Restart gateway
    await runWsl("tmux kill-session -t rag-gateway 2>/dev/null; sleep 1");
    await runWsl(
      "tmux new-session -d -s rag-gateway 'cd /opt/global-rag && source venv/bin/activate && python3 rag_gateway.py --port 9100 --host 0.0.0.0'"
    );
    // Restart Weaviate
    await runWsl("cd /opt/global-rag/stack && docker compose restart weaviate 2>/dev/null");
    // Restart Gemma
    await runPs(
      `& "D:\\ai\\qwen-code\\bin\\global-rag-system\\scripts\\gemma\\manage-gemma.ps1" -Action restart -Profile q4`
    );
    return NextResponse.json({
      ok: true,
      message: "全部服务重启中，请稍候",
    });
  }

  return NextResponse.json({ error: "未知服务" }, { status: 500 });
}