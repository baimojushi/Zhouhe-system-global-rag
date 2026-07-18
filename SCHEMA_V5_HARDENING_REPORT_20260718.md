# Knowledge Workbench Schema V5 加固与交付说明

## 结论

本版以用户上传的 Schema V4 源码为业务基线，完成第三阶段的发布门禁和前端审核闭环。V5 不改变已有 Library、Document、Document Version、Placement 和 Weaviate Collection 的稳定 ID；Gateway 首次打开控制数据库时会在同一个 SQLite 事务中补齐新增列，并把 `schema_meta.schema_version` 更新为 `5`。

## 修复的问题

| 范围 | V4 风险 | V5 行为 |
| --- | --- | --- |
| Schema | 已有提案表但版本仍报告 3 | 显式迁移至 Schema 5，迁移可重复运行 |
| 提案项审核 | 只检查 `pending`，不检查版本锁 | 批准时校验版本、文档修订、主目录和目标节点 |
| 批量应用 | 可部分移动，目标节点可能已失效 | `BEGIN IMMEDIATE` 全量预检；全部成功或全部回滚 |
| 撤销 | 会覆盖后续人工编辑或移动 | 校验应用后的版本、修订和目录；存在后续修改则返回 409 |
| 路由卡 | 写入 `document_id`，回退器读取 `file_id` | 两个字段均使用真实 Document ID，不再猜测前缀 |
| 目录输入 | LLM 使用静态预制树 | 使用实时树并压缩为 node ID、名称、说明和子节点，降低 Token |
| Worker 租约 | 过期 Worker 仍可能完成任务 | 完成、失败和激活均校验 Worker ID 与有效租约 |
| Worker 崩溃 | 过期租约不消耗重试次数 | 每次过期消耗一次预算，达到上限进入 failed |
| 版本激活 | 完成 Version、激活 Document、完成 Job 分三次提交 | `finalize_ingest_job()` 在同一个 SQLite 事务中完成 |
| 重试写入 | Chunk 没有确定 UUID | UUID 由 version ID 与 chunk index 确定，避免重试制造新对象 |
| 检索过滤 | 每次请求发送全部 active version ID | 小集合仍在 Weaviate 过滤；大集合改为有界过取并在 Gateway 严格后过滤 |
| 前端 | 只有一次性“预览”条幅 | 持久化提案历史、逐项批准/拒绝、原子应用、安全撤销、冲突提示 |

## API

新前端使用以下 V2 路径，旧 `/v1/taxonomy/proposals` 路径继续兼容：

- `GET /v2/ai-proposals?library_id=...`
- `GET /v2/ai-proposals/{proposal_id}`
- `POST /v2/ai-proposals`
- `POST /v2/ai-proposals/{proposal_id}/items/{item_id}/approve`
- `POST /v2/ai-proposals/{proposal_id}/items/{item_id}/reject`
- `POST /v2/ai-proposals/{proposal_id}/apply`
- `POST /v2/ai-proposals/{proposal_id}/revert`

所有写接口复用 `RAG_GATEWAY_API_KEY` Bearer 鉴权。版本锁、目录变化或撤销冲突返回 HTTP 409；输入不合法返回 400。

## 安全升级步骤

1. 停止 Gateway 和 Ingest Worker，Weaviate 可继续运行。
2. 备份 `/opt/global-rag/data/knowledge-control.db` 及其 `-wal`、`-shm` 文件；最稳妥的方式是在停止进程后复制整个 `data` 目录。
3. 替换源码，但保留现有 `.env`、控制数据库、知识文件和 Weaviate 数据卷。
4. 启动一次 Gateway。`KnowledgeStore` 会自动把 V3/V4 元数据迁移到 V5，不需要手工执行 SQL。
5. 验证 `GET /v2/control/health` 中 `schema_version` 为 `5`。
6. 启动 Ingest Worker，再启动前端。
7. 在“知识资产工作台 → 提案队列”中打开历史提案。旧提案可以读取；应用前仍会接受 V5 的实时冲突检查。

V4 已经处于 `applied` 状态的历史提案没有 `applied_document_revision`，V5 会拒绝自动撤销这类记录，避免猜测并覆盖后续人工修改。需要撤销时应依据升级前备份和审计记录人工处理。

若需要回退，必须先停止 Gateway/Worker，再恢复升级前的控制数据库备份和旧源码。不要仅把 `schema_meta` 手工改回 4。

## 验证命令

```bash
npm run typecheck
npm run lint
npm run test:backend
npm run build
npm start
npm run verify:ui
```

当前回归集包含 17 项，覆盖早期 V4 缺列迁移、Schema 重入、提案归属、不可写目标、重复项、逐项审核、幂等应用/撤销、批次原子性、人工修改后的撤销冲突、Worker 所有权、过期租约重试预算和原子版本激活。

本次实际验证结果：Python 编译通过；17 项后端回归通过；TypeScript 类型检查通过；ESLint 0 错误、0 警告；Webpack 生产构建通过；standalone 生产服务自检通过，主页、CSS、6 个客户端 JS chunk、知识工作台样式和 ESO ALPACA 夜空资源均返回正常。验证容器本身无法读取 RSS，因此构建时使用了容器外置的临时 `process.memoryUsage` 兼容垫片，该文件未放入项目和交付包。

项目构建脚本固定使用 `next build --webpack`，用于规避已在 Windows 上观察到的 Turbopack client chunk 404。`npm start` 会在启动 standalone 前复制 `.next/static` 和 `public`，不能直接跳过该脚本运行 `.next/standalone/server.js`。

## 检索扩展性说明

`RAG_ACTIVE_FILTER_THRESHOLD` 默认是 `256`：

- active version 数量不超过阈值时，Gateway 使用 Weaviate `contains_any`；
- 超过阈值时，Gateway 最多取回 500 个候选，再用 SQLite 当前版本集合进行严格过滤；不会返回旧版本，但极端历史版本密度下可能少于 `top_k`。

后续若单库达到十万级版本，建议实施 Weaviate `is_active` 标志加持久化 outbox/reconciler。本版没有用跨 SQLite/Weaviate 的伪“分布式事务”换取表面上的实时标志，以免失败时把旧版本错误暴露给检索。

## 源码恢复说明

本次上传的 ZIP 在 `public/sky/alpaca-snapshot.webp` 中途截断，缺少中央目录。`app/`、`backend/`、Schema V4、Worker、提案代码和测试均已按本地文件头、解压长度与 CRC 完整恢复；截断点之后的静态资源和启动脚本由上一份同项目基线补齐。所有本轮业务改动均建立在本次上传且 CRC 验证通过的源码上。
