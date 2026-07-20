# Windows E:\RAG 原始资料目录说明

## 固定目录

Windows 原始资料根目录固定为 `E:\RAG`，WSL2 中对应 `/mnt/e/RAG`。

系统只创建四个保存原文的一级目录：

| Windows 目录 | WSL2 目录 | 知识库 | 新文件入口 |
| --- | --- | --- | --- |
| `E:\RAG\AI工作记录` | `/mnt/e/RAG/AI工作记录` | `ai-work` | `ai-unclassified` |
| `E:\RAG\学术资料` | `/mnt/e/RAG/学术资料` | `academic` | `ac-unclassified` |
| `E:\RAG\生产文档` | `/mnt/e/RAG/生产文档` | `production` | `pr-unclassified` |
| `E:\RAG\个人思维笔记` | `/mnt/e/RAG/个人思维笔记` | `notes` | `nt-unclassified` |

关联知识库不保存原始文件，因此不会创建 `E:\RAG\关联知识库`。

## 使用方法

1. 在 Windows 资源管理器中，把文件拖入对应一级目录或其任意子目录。
2. 打开“知识库管理”，选择相同的知识库。
3. 等待系统每 5 分钟自动扫描，或点击“立即扫描”。
4. 新发现的文件进入该知识库的“待整理/未归类”节点。
5. 在“导入进度”查看切片、向量化和写入结果。

自动扫描会先记录文件大小和修改时间，等待 30 秒后再次确认；只有两次完全一致的文件才会入队，避免复制到一半就被读取。重复扫描同一个未变化的文件会复用原任务，不重复索引；文件大小或修改时间变化后会创建新版本任务。扫描不会删除或移动 Windows 原文件。

## 安全边界

- Gateway 和 Worker 默认只允许读取 `/mnt/e/RAG`。
- 扫描不跟随符号链接，不读取隐藏目录和隐藏文件。
- 当前扫描只接收文本、Markdown、代码、JSON/YAML、CSV、HTML/XML 等可安全按文本解析的格式。
- 单文件默认上限为 100 MiB；不支持的文件会被跳过，而不是作为乱码索引。
- 写操作继续受 `RAG_GATEWAY_API_KEY` 保护。

## 服务环境变量

```bash
RAG_INGEST_ROOTS=/mnt/e/RAG
RAG_CONTROL_DB=/opt/global-rag/data/knowledge-control.db
RAG_AUTO_SCAN_SECONDS=300
RAG_FILE_STABILITY_SECONDS=30
```

`scripts/restart-all-services.ps1` 会创建 Windows 目录，并同时启动 Gateway 与 `ingest_worker.py`。停止脚本会停止 Worker，但不会删除 `E:\RAG` 中的任何文件。
