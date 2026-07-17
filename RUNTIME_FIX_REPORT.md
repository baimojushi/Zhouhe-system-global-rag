# 前端交互故障修复说明

基线：`master@9b95b8d428e7954978391bbe91cfb119bad1dff8`。

## 2026-07 Gemma 架构补充

- 前端服务命名与默认设置已从 Ollama/vLLM/Qwen 迁移为 Gateway 内置 BGE-M3 与 llama.cpp Gemma 4 31B Q4。
- 旧浏览器设置中的 `vllmUrl` 会迁移到 `llmUrl`；旧 Ollama `embeddingUrl` 不再显示。
- 当前 Gemma 默认端口按实际启动器统一为 `8000`，未来 `8010` 规划改为可配置迁移目标。
- 新增 `scripts/restart-all-services.cmd` / `.ps1`，统一启动并检查 Weaviate、Gemma、Gateway 和 GUI。
- 新增 `scripts/stop-all-services.cmd` / `.ps1`，并将 Gemma Q4/Q8 启停改为源码内自包含管理器；正式流程不再依赖 `F:\scripts\Gemma`。
- 修复原始 Gemma 脚本的全局误杀、硬编码 WSL 参数、无效停止匹配和不精确进程健康检查问题。
- 完整下一版本问答/分类器目标和原始详细方案已纳入源码；当前 Gateway 尚未实现 `/v1/qa` 与 `/v1/qa/stream`，不得将规划状态误报为已上线。

## 修复范围

- 修正 Windows standalone 启动脚本的硬编码路径与错误静态目录。
- 所有本地生产启动统一进入 `scripts/start-local.mjs`，启动前复制
  `.next/static` 和 `public`。
- 将 Turbopack 根目录固定为当前项目，避免父目录 lockfile 影响嵌套部署。
- 将 RAG Gateway 文档默认端口统一为 9100。
- 浏览器保存值仅在精确匹配旧默认 8090 时自动迁移到 9100。
- UI 自检增加全部客户端 `<script src>` 的 HTTP 状态和媒体类型验证。
- 增加 `npm run dev:webpack`，用于隔离 Turbopack 与本地代理/进程问题。
- 删除测试脚本中的硬编码 Weaviate 密钥，改读 `WEAVIATE_API_KEY`。

## Windows 恢复步骤

```bat
cd /d D:\ai\qwen-code\bin\global-rag-system
rmdir /s /q .next
npm ci
npm run build
npm start
```

另开终端：

```bat
cd /d D:\ai\qwen-code\bin\global-rag-system
npm run verify:ui
```

验收条件：主页、所有 CSS、所有客户端 JS、夜空元数据和背景图片均返回有效内容，
终端输出“UI 自检通过”。

## 安全处置

旧 Weaviate API Key 已进入公开 Git 历史，源码修复不能使其重新安全。部署方必须：

1. 立即吊销旧 Key 并生成新 Key。
2. 将新 Key 只放入环境变量或本机未跟踪的 `.env`。
3. 使用 `git-filter-repo` 清理历史并协调所有克隆更新。
4. 确认旧 Key 已无法访问 Weaviate 后再恢复外部连接。
