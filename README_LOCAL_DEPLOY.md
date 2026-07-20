# 全局 RAG 检索工作台：本地部署

这是 GUI 的完整本地部署包。默认开启演示模式，无需后端即可检查所有页面和交互；切换到“本地服务”后，界面会调用 WSL2 中的 RAG Gateway、Weaviate 和 llama.cpp Gemma。BGE-M3 已内置于 Gateway，不再作为 Ollama/独立端点配置。

原始资料统一保存在 Windows `E:\RAG`，WSL2 对应路径为 `/mnt/e/RAG`。一键启动会建立“AI工作记录、学术资料、生产文档、个人思维笔记”四个文件夹，并启动摄取 Worker；关联知识库不创建原始文件目录。

摄取 Worker 默认每 300 秒扫描一次，并用 30 秒窗口确认文件已经复制稳定。可通过 `RAG_AUTO_SCAN_SECONDS` 和 `RAG_FILE_STABILITY_SECONDS` 调整；将前者设为 `0` 可关闭自动扫描，但前端“立即扫描”仍可使用。

## 一、直接使用 Node.js（推荐开发和调试）

要求：Node.js 22.13 或更高版本。

```bash
cd global-rag-console-local

# 大陆网络可选
npm config set registry https://registry.npmmirror.com

npm ci
npm run build
npm start
```

浏览器打开：<http://127.0.0.1:3000>

保持服务运行，再开一个终端执行界面自检：

```bash
npm run verify:ui
```

只有出现“UI 自检通过”才表示主页与 CSS 产品样式均部署成功。仅能看到文字、默认按钮和纵向堆叠内容，不属于正常界面。

Windows 也必须从项目根目录运行 `npm start`。不要直接执行
`node .next\standalone\server.js`；standalone 默认不包含 `public` 与
`.next\static`，直接启动会出现“主页 200、客户端 JS/CSS 全部 404”。也可以双击
`scripts\start-standalone-fix.cmd`，该脚本会定位自身所在项目并调用同一启动入口。

开发模式：

```bash
npm run dev
```

默认只监听本机。如确实需要从局域网访问开发服务器，可显式运行 `npm run dev:lan`，并先确认 Windows 防火墙和访问控制；不要把它用于不可信网络。

如果只在 Turbopack 开发模式下出现客户端 chunk 404，可停止开发服务后使用 Webpack
进行隔离诊断：

```bash
npm run dev:webpack
```

## 二、使用 Docker Compose

```bash
cd global-rag-console-local
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml logs -f
docker compose -f docker-compose.local.yml ps
```

浏览器打开：<http://127.0.0.1:3000>

停止 GUI：

```bash
docker compose -f docker-compose.local.yml down
```

Compose 同时启动 GUI 和 `sky-updater`。后者每小时查询 ESO ALPACA，将最新合格科学帧转换为 4K WebP 并写入只读共享卷；更新失败不会覆盖上一帧。RAG 请求仍由浏览器发起，所以设置中的后端地址填写 `127.0.0.1`，不要填写 Docker 容器名。

容器内置 UI 健康检查；`docker compose ... ps` 应显示 `healthy`。如果升级后仍显示旧页面，使用无缓存方式重建：

```bash
docker compose -f docker-compose.local.yml build --no-cache
docker compose -f docker-compose.local.yml up -d --force-recreate
```

## 三、连接真实后端

### 一键重启全部依赖

默认环境与本机约定一致时，双击：

```text
scripts\restart-all-services.cmd
```

它会依次处理并检查 `8080/50051`（Weaviate）、`8000`（Gemma Q4）、`9100`（Gateway + BGE-M3）和 `3000`（GUI），最后运行完整 JS/CSS 资源自检。首次启动或源码更新后使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart-all-services.ps1 -Build
```

Gemma 启动器和 Linux 服务管理器都已包含在 `scripts\gemma` 中，不依赖原来的 `F:\scripts\Gemma`。WSL 发行版、用户、Q4/Q8 档位和端口均可通过 PowerShell 参数覆盖；完整参数见脚本顶部。

停止全部服务可双击：

```text
scripts\stop-all-services.cmd
```

它只停止 PID 和命令行身份都能确认属于本项目的进程；若 `3000` 被其他程序占用，会提示但不会误杀。加 `-KeepWeaviate` 可只停止 GUI、Gateway 和 Gemma，保留数据库运行。

打开 GUI 的“设置”，关闭“演示模式”，确认以下默认端点：

| 服务 | 默认地址 |
|---|---|
| RAG Gateway | `http://127.0.0.1:9100` |
| Weaviate | `http://127.0.0.1:8080` |
| BGE-M3 | Gateway 进程内，无独立浏览器端点 |
| llama.cpp Gemma Q4 | `http://127.0.0.1:8000` |

填入 Gateway/Weaviate API Key 和 llama.cpp 的实际模型别名，然后保存并测试连接。当前正式启动入口为源码内 `scripts\gemma\manage-gemma.ps1`；Q4 默认 `8000`，Q8 默认 `8002`。方案中的 `8010/8011` 是未来端口规划，不是当前运行值。

设置只保存在浏览器 `localStorage` 中，不会写入源码。高安全环境不建议让浏览器长期保存管理级密钥；可由 Gateway 使用单独的前端低权限令牌。
升级后，界面会将精确匹配旧默认值 `127.0.0.1:8090` 或 `localhost:8090`
的浏览器设置迁移到 9100；用户自己填写的其他地址不会被覆盖。

## 四、Gateway API 约定

部署文档只定义了端点，没有固定 JSON 字段。本 GUI 使用以下约定。

### 检索

`POST /v1/retrieve`

```json
{
  "query": "WSL2 中的部署与故障排查",
  "scope": "global",
  "alpha": 0.65,
  "top_k": 6,
  "session_id": "local-main"
}
```

响应可以将数组放在 `results`、`items` 或 `data` 中。每一项建议包含：

```json
{
  "id": "chunk-id",
  "score": 0.94,
  "title": "文档标题",
  "heading": "章节标题",
  "content": "检索片段",
  "source_path": "/mnt/e/RAG/生产文档/example.md",
  "source_name": "example.md",
  "page": 12,
  "scope": "global",
  "mime_type": "text/markdown"
}
```

也支持 Weaviate 风格的 `{ "properties": { ... } }` 包装。

### 入库和记忆

- `POST /v1/ingest/path`：`{ "path": "...", "library_id": "production", "target_node": "production-unclassified", "classification": "manual-major-category" }`
- `POST /v1/ingest/text`：`{ "title": "...", "content": "...", "scope": "private" }`
- `POST /v1/memory`：`{ "content": "...", "session_id": "...", "memory_type": "decision", "importance": 0.8, "scope": "private" }`
- `POST /v1/taxonomy/proposals`：生成目录变更预览，不移动文件。
- `POST /v1/taxonomy/proposals/:id/apply`：使用目录版本锁应用人工确认的变更。
- `POST /v1/associations/discover`：生成跨库候选关系边。
- `GET /health`

如果现有 Gateway 字段不同，只需调整 `app/page.tsx` 中的 `runSearch` 和 `postGateway`。

## 五、配置 CORS

浏览器必须获得 Gateway 的跨域许可。FastAPI 示例：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

下一版本建议浏览器只访问 Gateway，由 Gateway 代为访问 Weaviate、进程内 BGE-M3 和 llama.cpp Gemma。当前 GUI 的健康检查仍会直接读取 Weaviate 与 Gemma 端点，因此这些服务若未开放 CORS，只有相应状态检查会显示离线，不影响通过 Gateway 检索。问答/分类器接口迁移完成后，将一并收敛健康检查。

## 六、安全建议

- 所有端口仅绑定 `127.0.0.1`。
- Gateway 强制校验 `scope` 和 `session_id`。
- 不把 Weaviate 管理密钥写入前端源码或 Docker 镜像。
- 后端测试脚本从环境变量 `WEAVIATE_API_KEY` 读取密钥；仓库中的 `.env.example`
  只能放占位符，真实 `.env` 不得提交。
- 生产使用时让 Gateway 提供健康状态聚合，减少浏览器直接访问底层服务。
- MCP 写入接口保持关闭，知识库管理操作只允许人工界面调用。

运行后端导入测试前，在当前终端注入新密钥：

```powershell
$env:WEAVIATE_API_KEY = "替换为已轮换的新密钥"
python backend/test_import.py
```

测试结束后可执行 `Remove-Item Env:WEAVIATE_API_KEY` 清除当前 PowerShell 会话中的变量。

## 七、界面样式故障排查

如果页面退化成浏览器默认样式：

1. 先运行 `npm run verify:ui`，不要继续进行业务验收。自检会逐一请求 HTML 中的
   CSS 与客户端 JS，并拒绝 404 或错误媒体类型。
2. 浏览器按 `Ctrl+F5` 强制刷新，排除旧 HTML 与旧 CSS 缓存混用。
3. 打开开发者工具的 Network，确认 `/_next/static/` 下的 CSS 和 JS 均返回 HTTP 200，
   且不是 HTML 错误页。
4. 使用 Docker 时按上面的无缓存命令重建，避免复用旧镜像层。
5. 如果前面还有 Nginx，必须把 `/_next/` 与主页代理到同一个 GUI 服务，不要只代理 `/`。
6. 项目若嵌套在另一个 Node.js 工作区中，`next.config.ts` 已固定 `turbopack.root`
   为当前项目目录，避免父目录 lockfile 干扰模块解析。

本地部署已使用标准 Next.js 运行链，不需要 Vinext、Vite 或 Tailwind 运行时。

## 八、真实夜空夜间模式

顶部工具栏的“深空模式”用于切换红黑透明舷窗主题。主题选择与视觉参数保存在当前浏览器，不改变后端服务配置。

夜空数据来自 ESO ALPACA 实拍 FITS，UI 显示观测 ID、UTC 拍摄时间、原始像素和 `sqm_zen`。完整更新与降级策略见 `REALTIME_SKY_BACKGROUND.md`。

可在“设置 → 深空显示参数”调节：

- 科研原图 / 氛围增强：默认科研原图不添加合成星；开启后才启用以下三个模拟参数。
- 星场密度：控制氛围增强层中的程序化星点数量。
- 极限视星等：范围 `5.0–9.0 m`；数值越高，模拟层加入的暗星越多。
- 闪烁幅度：只改变氛围层的微弱亮度波动，周期保持在约 20–60 秒。
- 玻璃不透明度：控制功能容器的遮罩强度；页面间隙始终完全透明。
- 银河曝光：控制真实全天空帧的显示亮度，不改写原文件。

系统开启“减少动态效果”时，星场会自动停止闪烁并保持静态。背景图片的来源与署名见 `THIRD_PARTY_ASSETS.md`。

## 九、知识库工作台

管理界面采用已确认的 A 方案：多级目录树、每库独立 collection、工作台 + 详情抽屉。预制大类包括 AI 工作记录、学术资料、生产文档、个人思维笔记与关联知识库。

新文件先由用户选择前四个文档库之一，并进入该库的“未归类”。只有点击“AI 自动归类”后才调用远程闭源模型；返回结果先在详情抽屉预审，低置信度内容继续保留未归类。关联知识库只存跨库关系边和证据指针。

后端数据模型、API、隐私边界和每批 Token 预算见 `BACKEND_KNOWLEDGE_ITERATION_PLAN.md`。
