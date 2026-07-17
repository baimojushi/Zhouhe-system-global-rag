import { cp, stat } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));

async function exists(path) {
  try { await stat(path); return true; }
  catch { return false; }
}

const root = resolve(scriptDir, "..");
const standalone = resolve(root, ".next/standalone");

if (!(await exists(resolve(standalone, "server.js")))) {
  console.error("没有找到生产构建，请先运行 npm run build。");
  process.exit(1);
}

await cp(resolve(root, ".next/static"), resolve(standalone, ".next/static"), { recursive: true, force: true });
await cp(resolve(root, "public"), resolve(standalone, "public"), { recursive: true, force: true });

process.env.HOSTNAME = process.env.UI_HOSTNAME ?? "127.0.0.1";
process.env.PORT ??= "3000";

// Windows 下 ESM import 需要 file:// 协议
const serverUrl = pathToFileURL(resolve(standalone, "server.js")).href;
await import(serverUrl);
