# Knowledge Workbench V2 第一阶段落地报告

> 本文是第一阶段历史报告。Worker、版本链和 AI 提案第三阶段现已完成并在 Schema V5 加固，当前升级说明以 `SCHEMA_V5_HARDENING_REPORT_20260718.md` 为准。

## 本轮交付范围

本轮实现 V2 的“手动管理基础闭环”，没有宣称完成后续 AI 目录治理和潜在关联推理：

- SQLite WAL 持久化控制面。
- 五个预制知识库和可创建的自定义知识库。
- 动态任意层级目录树。
- 目录创建、编辑、拖拽移动、锁定和安全归档。
- 独立 Document、Document Version 和 Placement。
- 文档唯一主归属、目录别名、标签和批量移动。
- 持久化摄取任务、审计事件和变更集。
- 现有 Weaviate `KnowledgeChunk` 到 V2 Document 的幂等迁移工具。
- 四区知识资产工作台：库导航、目录树、文档表格、检查器。

## 关键文件

| 文件 | 作用 |
| --- | --- |
| `backend/knowledge_store.py` | V2 SQLite 数据模型、约束和领域操作 |
| `backend/rag_gateway.py` | V2 REST API、路径安全、鉴权兼容和 V1 修复 |
| `backend/migrate_v2_control.py` | 现有向量数据的只读扫描和控制面迁移 |
| `backend/test_knowledge_store.py` | 持久化、版本冲突、循环移动、归档、别名、标签和分页回归测试 |
| `app/knowledge-workbench.tsx` | 动态知识库管理前端 |
| `app/globals.css` | 四区布局、文档表格、弹窗及红黑透明夜间样式 |

## 历史错误回归约束

1. Weaviate Schema 只使用 `DataType.INT`，没有 `INT64`。
2. 批量写入使用 `insert_many`，没有 `insert_batch`。
3. Gateway 直接运行所需模块全部使用绝对导入。
4. 保留 `CORSMiddleware` 和 3000 端口来源。
5. 保留 `--host` 参数；Uvicorn 直接使用现有 `app`，避免二次导入。
6. V1 提案兼容逻辑仍按实际 `scope=global` 搜索；V2 不再用 scope 推断文档归属。
7. 新前端类型不再依赖固定 `LibraryId` 联合类型。
8. Gateway 泛型请求返回明确的 Promise 类型，不使用 nullable 强转链。
9. 可选提案字段均使用空值默认值。
10. 库统计字段由 V2 API 统一返回。
11. 原重启 API 已使用 `spawn("wsl.exe", [...])`，没有经 PowerShell 拼接 WSL 命令。
12. 未手工修改 `next-env.d.ts`。

## 验证结果

- `python3 -m unittest backend/test_knowledge_store.py -v`：8 项通过。
- `python3 -m py_compile backend/*.py`：通过。
- `npx tsc --noEmit`：通过。
- `npm run lint`：V2 新代码无错误；基线 `app/page.tsx` 仍有一个未使用变量警告。
- `npm run build`：Next.js 16.2.6 生产构建通过。

验证环境本身无法读取进程 RSS，原生 `process.memoryUsage()` 会抛出 `uv_resident_set_memory`。构建验证时仅通过临时运行时覆盖规避该容器限制，覆盖文件没有进入交付源码。此问题不是项目代码或 Windows/WSL 部署问题。

## 第一阶段结束时尚未完成

- 摄取 Worker 消费 V2 Job 并按库写入独立 Weaviate Collection。
- Document Version 的内容替换、解析和原子索引切换。
- AI 提案逐条勾选、编辑、Schema 校验、应用和回滚。
- 潜在关联边、证据、审核和检索扩展。
- 目录 Closure Table、节点权限继承和智能目录查询构建器。

上述内容应在当前控制面稳定运行并完成现有 87 条数据迁移验证后继续实施。
