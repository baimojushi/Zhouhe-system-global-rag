# MinerU 解析后、向量入库前的 PDF 智能重命名执行文档

## 1. 目标与最终时序

本功能解决 `E:\RAG` 中 PDF 文件名残缺、下载站后缀冗余、作者/年份格式不统一，以及平铺目录中难以人工浏览的问题。

最终时序固定为：

1. Windows 用户将 PDF 放入 `E:\RAG` 四类目录之一。
2. 自动扫描等待文件大小和修改时间稳定 30 秒。
3. SQLite 创建 Document、Document Version 和 Ingest Job。
4. Worker 将 PDF 提交给本机 MinerU `http://127.0.0.1:18000`。
5. MinerU 产出 `document.md`、`content_list.json` 和 `manifest.json`。
6. 本地 Gemma 读取经过长度限制的 MinerU 结构化文字，只生成严格 JSON 命名提案。
7. 系统校验置信度、标题、文件名安全性和目标冲突。
8. 在原目录内重命名 PDF，并在一个 SQLite 事务中同步 Document、Version、Ingest Job 和幂等键。
9. Worker 使用新文件名生成 Chunk 元数据、BGE-M3 向量并写入 Weaviate。
10. 所有 Chunk 成功后才原子激活新版本。

Gemma 不读取 PDF 二进制，也不在 MinerU 之前猜测书目信息。扫描型 PDF 同样可以使用 MinerU OCR 结果命名。

## 2. 文件命名规范

默认格式：

```text
[文档类型] 标题 - 第一作者或主要机构 - 年份 - 版次.pdf
```

示例：

```text
[论文] Evidence-Aware Retrieval for Long Documents - Li Ming - 2025.pdf
[专著] 信息检索导论 - 张三 - 2022 - 第2版.pdf
[报告] 人工智能发展年度报告 - 某研究院 - 2026.pdf
[标准] 信息技术安全要求 - 国家标准化机构 - 2024.pdf
```

规则：

- 类型限定为：论文、专著、综述、学位论文、报告、标准、手册、资料。
- 缺失作者、年份或版次时直接省略，不填“未知”。
- 不翻译标题，不补写模型无法从 MinerU 内容验证的信息。
- creator 只保留第一作者或主要机构，避免文件名过长。
- 扩展名统一为小写 `.pdf`。
- Windows 禁止字符 `< > : " / \ | ? *` 会被移除。
- 连续空格折叠，尾部点号和空格移除。
- 文件名最长默认 180 字符。
- 已符合规范的文件不再调用 Gemma。
- 同名目标不会覆盖；自动增加源文件 SHA-256 前 8 位，例如 `[a1b2c3d4]`。

## 3. Gemma 输入输出契约

Gemma 使用 llama.cpp 的 OpenAI 兼容接口：

```text
POST http://127.0.0.1:8000/v1/chat/completions
```

输入只包括：

- 原始文件名；
- MinerU `document.md` 的有限长度摘录；
- `content_list.json` 前部的页码、块类型和文字；
- 系统防注入规则。

Gemma 必须返回：

```json
{
  "decision": "rename",
  "document_type": "paper",
  "title": "Evidence-Aware Retrieval for Long Documents",
  "creator": "Li Ming",
  "year": "2025",
  "edition": "",
  "confidence": 0.96,
  "reason": "论文首页给出标题、作者与年份"
}
```

`decision=hold`、JSON 无效、标题过于宽泛或置信度低于阈值时，系统保留原名。

## 4. 环境变量

```dotenv
RAG_PDF_AUTO_RENAME=true
RAG_PDF_RENAME_API_BASE=http://127.0.0.1:8000/v1
RAG_PDF_RENAME_MODEL=gemma-4-31b-q4
RAG_PDF_RENAME_API_KEY=
RAG_PDF_RENAME_MIN_CONFIDENCE=0.82
RAG_PDF_RENAME_TIMEOUT_SECONDS=60
RAG_PDF_RENAME_MAX_EXCERPT_CHARS=16000
RAG_PDF_RENAME_FAIL_CLOSED=false
RAG_PDF_RENAME_ALLOW_REMOTE=false
RAG_PDF_RENAME_LOCK_FILE=/opt/global-rag/run/pdf-rename.lock
```

一键启动脚本会根据 Q4/Q8 档位自动设置端口和模型别名：

| 档位 | 地址 | 模型别名 |
|---|---|---|
| Q4 | `http://127.0.0.1:8000/v1` | `gemma-4-31b-q4` |
| Q8 | `http://127.0.0.1:8002/v1` | `gemma-4-31b-q8` |

默认只允许 loopback 地址，避免 PDF 内容间接触发外部数据发送。

## 5. 数据库 Schema V8

新增 `file_rename_events`，记录：

- 所属知识库、Ingest Job、Document 和 Version；
- 文件内容 SHA-256；
- 旧路径、新路径、旧名称、新名称；
- proposed、applied、unchanged、skipped、failed 状态；
- Gemma 模型、置信度、理由和原始提案；
- 错误、操作者和时间。

实际文件重命名后，同一个 SQLite 事务同步：

```text
documents.source_path / source_name / title
document_versions.source_uri
ingest_jobs.source_path / idempotency_key
file_rename_events.state
audit_events
```

更新 `idempotency_key` 很重要：否则五分钟后的自动扫描会把新路径误判为一份新版本。

## 6. 故障与回退策略

| 故障 | 默认行为 |
|---|---|
| Gemma 未启动或超时 | 保留原名，记录 skipped，继续向量入库 |
| MinerU 内容不足 | 保留原名，不允许 Gemma猜测 |
| Gemma JSON 非法或低置信度 | 保留原名并审计 |
| 目标名称已存在 | 加内容哈希后缀，绝不覆盖 |
| 重命名后 SQLite 事务失败 | 尝试把物理文件改回旧名，记录 failed，任务失败重试 |
| Worker 在文件改名后、SQLite 提交前崩溃 | 启动时扫描 proposed 事件；若新路径存在且旧路径消失，自动补交路径事务 |
| Worker 在 SQLite 提交后崩溃 | Job 中的新路径和新幂等键已经持久化；重试时直接使用规范名称 |
| Weaviate 写入失败 | 原文件和 SQLite 已使用规范名称，现有版本不会被激活；重试索引即可 |
| 已符合规范 | 不调用 Gemma，直接进入索引 |

如希望“Gemma 无法命名就禁止入库”，设置：

```dotenv
RAG_PDF_RENAME_FAIL_CLOSED=true
```

默认建议保持 `false`，避免命名辅助功能阻断核心知识入库。

## 7. API 与运维检查

功能状态：

```bash
curl -s http://127.0.0.1:9100/v2/ingest/layout
```

响应中应包含：

```json
{
  "pdf_auto_rename": true,
  "pdf_rename_stage": "after_mineru_before_index",
  "pdf_rename_min_confidence": 0.82
}
```

查看重命名历史（需要管理认证）：

```bash
curl -H "Authorization: Bearer $RAG_GATEWAY_API_KEY" \
  "http://127.0.0.1:9100/v2/file-rename-events?library_id=academic&limit=50"
```

日志：

```bash
tail -f /opt/global-rag/logs/ingest_worker.log
```

成功记录示例：

```text
PDF filename stage: job=job-... state=applied name=[论文] ... - 2025.pdf
```

## 8. 部署步骤

1. 备份：

   - `E:\RAG`
   - `/opt/global-rag/data/knowledge-control.db*`
   - `/opt/global-rag/.env`

2. 用新版源码覆盖程序文件，不覆盖 `E:\RAG`、SQLite 数据库、Weaviate 数据卷和密钥。
3. 执行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\restart-all-services.ps1 -Build
   ```

4. 放入一份测试 PDF，等待稳定检测、MinerU、Gemma 和索引完成。
5. 检查 Windows 文件名、重命名事件 API、Document 路径和检索结果标题一致。

Schema V7 数据库会自动迁移到 V8，不需要手工执行 SQL。

## 9. 验收用例

- 电子论文：正确识别标题、第一作者和年份。
- 扫描型专著：使用 MinerU OCR 结果命名。
- 中英混合标题：不翻译、不破坏原始大小写。
- 低置信度材料：保留原名并产生 skipped 事件。
- 同名 PDF：原文件不被覆盖，新文件带稳定哈希后缀。
- Gemma 服务关闭：PDF 仍可入库，任务不永久卡住。
- SQLite 提交失败：文件名回滚，不能出现磁盘路径和数据库路径分裂。
- 重命名后 Worker 重启：不重复调用和不重复创建 Document Version。
- 下一轮自动扫描：复用原 Ingest Job，不产生重复版本。

## 10. 当前范围

- 自动重命名只作用于新进入 MinerU 流水线的 PDF。
- 已经完成入库的历史 PDF 不会被批量自动改名，避免破坏现有引用；后续可单独增加“历史文件命名提案与人工审批”功能。
- 本功能调整文件系统名称和检索展示名称，不改变文档逻辑分类。
