# 全局 RAG 检索工作台

连接 Weaviate、进程内 BGE-M3、RAG Gateway 与 llama.cpp Gemma 的本地 GUI。

完整安装、Docker、API 和 CORS 说明见 [README_LOCAL_DEPLOY.md](README_LOCAL_DEPLOY.md)。
固定依赖版本见 [DEPENDENCY_MANIFEST.md](DEPENDENCY_MANIFEST.md)。
本次 master/runtime 合并内容与验证结果见 [MERGE_REPORT_20260717.md](MERGE_REPORT_20260717.md)。

快速启动：

```bash
npm ci
npm run build
npm start
```

然后打开 <http://127.0.0.1:3000>。服务启动后可在另一个终端运行
`npm run verify:ui`，同时验证主页、产品样式和全部客户端 JS 资源是否正常。
Windows 不要直接运行 `.next\standalone\server.js`；请使用 `npm start` 或
`scripts\start-standalone-fix.cmd`，确保 standalone 静态资源复制完整。

在已按本机约定部署 `/opt/global-rag` 时，可直接双击 `scripts\restart-all-services.cmd`，依次重启 Weaviate、源码内置的 Gemma Q4 管理器、内置 BGE-M3 的 Gateway 和 Web GUI，并验证全部前端静态资源。它不再依赖 `F:\scripts\Gemma`。首次使用或源码更新后可运行 `powershell -ExecutionPolicy Bypass -File scripts\restart-all-services.ps1 -Build`。双击 `scripts\stop-all-services.cmd` 可停止 GUI、Gateway、Q4/Q8 和 Weaviate，不会执行 `wsl --shutdown` 或盲目结束无关端口进程。

顶部工具栏可切换“深空模式”。背景来自 ESO 帕拉纳尔 ALPACA 全天空相机的实际科学观测帧；Docker sidecar 每小时检查更新，当地白天或质量不合格时明确显示“最近可用夜空”。默认不叠加合成星，用户可选择开启带可调视星等和微弱闪烁的氛围增强层。实现与数据字段见 [REALTIME_SKY_BACKGROUND.md](REALTIME_SKY_BACKGROUND.md)，资产来源见 [THIRD_PARTY_ASSETS.md](THIRD_PARTY_ASSETS.md)。

知识库页面已升级为多级目录工作台，内置 AI 工作记录、学术资料、生产文档、个人思维笔记和关联知识库。闭源 AI 归类采用“手动大类 → 未归类 → 点击生成提案 → 人工确认”的流程，后端与 Token 预算见 [BACKEND_KNOWLEDGE_ITERATION_PLAN.md](BACKEND_KNOWLEDGE_ITERATION_PLAN.md)。

Schema V5 已补齐持久化提案历史、逐项批准/拒绝、版本锁冲突、原子应用与安全撤销，并加固 Worker 租约和版本激活。升级、API、回滚和验证步骤见 [SCHEMA_V5_HARDENING_REPORT_20260718.md](SCHEMA_V5_HARDENING_REPORT_20260718.md)。

下一版本地问答与问题分类器以 Gemma 4 31B GGUF / llama.cpp 为生成模型，BGE-M3 继续内置于 Gateway 负责向量化，不再依赖 Ollama 或 vLLM。完整落地方案见 [docs/Gemma4-31B-Vector-RAG-Implementation-Plan-CN.md](docs/Gemma4-31B-Vector-RAG-Implementation-Plan-CN.md)，本机端口与迁移目标见 [NEXT_VERSION_GEMMA_TARGET.md](NEXT_VERSION_GEMMA_TARGET.md)。
