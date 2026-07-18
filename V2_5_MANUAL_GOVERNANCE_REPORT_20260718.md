# V2.5 深度手动治理落地报告

本版本在 V2 三阶段控制面上补齐知识库的配套人工管理界面，并将控制库升级到 Schema V6。升级采用 SQLite 幂等迁移，不删除现有 Document、Version、Placement、Proposal 或审计数据；升级前仍建议备份 `RAG_CONTROL_DB`。

## 已落地能力

- 文档：生命周期筛选、标题/负责人/JSON 元数据编辑、标签勾选与新建、目录别名添加/删除。
- 版本：查看版本时间线、索引状态、块数、大小和哈希；将任一 ready 版本原子切换为活动版本。
- 任务：查看进度、Worker、重试次数和错误；安全取消 queued 任务；重试 failed/cancelled 任务。
- AI 提案：逐项审核、人工改派目标目录、改派后强制重新批准、顺序批量批准无冲突项、原子应用和安全撤销。
- 知识库：编辑名称、说明、检索/治理策略及 active/archived 状态。
- 审计：独立时间线页面，展示操作者、目标及变更数据。
- 关联知识库：跨不同文档库建立 candidate 关系，设置关系类型、置信度和人工说明，再确认或拒绝；只存指针和证据，不复制正文或向量。

## Schema V6

新增 `knowledge_edges`，包含关联库、来源/目标 Document ID、关系类型、置信度、候选状态、证据、乐观锁 revision 与审计字段。数据库约束禁止自关联、越界置信度和重复关系；业务层强制来源与目标属于不同文档库。

新增/补齐 API：

- `GET /v2/documents/{id}/versions`
- `POST /v2/documents/{id}/versions/{version_id}:activate`
- `POST /v2/jobs/{id}:retry`
- `POST /v2/jobs/{id}:cancel`
- `PATCH /v2/ai-proposals/{proposal_id}/items/{item_id}`
- `GET/POST /v2/knowledge-edges`
- `PATCH /v2/knowledge-edges/{id}`

所有写接口继续使用 Gateway 管理鉴权。任务取消不终止 running Worker；只允许取消尚未领取的 queued 任务，避免破坏写入事务。

## 验证结果

- `npm run typecheck`：通过。
- `npm run lint`：通过。
- `npm run test:backend`：18/18 通过（包含 V2.5 人工改派、任务控制和跨库关联回归）。
- `npm run build`：Next.js 16.2.6 webpack 生产构建通过。
- 基线包的 `npm run verify:ui` 已通过；V2.5 覆盖映射后的生产构建通过，部署到目标机后应按下节再次执行运行时自检。

## 部署后验证

```bash
python3 -m unittest backend/test_knowledge_store.py -v
npm ci
npm run build
npm start
```

另开终端执行 `npm run verify:ui`，然后检查 Gateway 的 `/v2/control/health` 返回 `schema_version: 6`。进入“知识资产工作台”，依次验证“目录与文档 / 摄取任务 / 审计记录”；选择“关联知识库”后验证“潜在关联”页。

生产升级前备份控制库；如需回退旧代码，必须同时恢复升级前的 SQLite 备份，不要让 Schema V5 程序直接写入已升级的 Schema V6 数据库。
