# 全局 RAG 检索工作台

连接 Weaviate、BGE-M3 与 vLLM 的本地混合检索系统。

## 项目结构

```
├── frontend/          # Next.js 前端 UI（React 19 + TypeScript）
│   ├── app/
│   │   ├── page.tsx           # 主页面：检索 / 知识库 / 记忆 / 状态 / 设置
│   │   ├── layout.tsx         # 根布局
│   │   └── globals.css        # 全局样式（配色、布局、响应式）
│   ├── package.json
│   ├── next.config.ts
│   └── tsconfig.json
│
├── backend/           # 后端服务
│   ├── rag_gateway.py         # Phase 3 — RAG API 网关（FastAPI）
│   ├── batch_indexer.py       # Phase 2 — 批量文档索引器（Docling + BGE-M3 + Weaviate）
│   ├── stack/
│   │   └── docker-compose.yml # Weaviate 1.38.3 服务定义
│   └── kb/                    # 知识库文档
│       ├── rag-architecture.md
│       ├── docker-guide.md
│       ├── wsl2-guide.md
│       └── rag-api-example.py
│
├── scripts/
│   └── verify-ui.mjs          # UI 自检脚本
│
├── Dockerfile.local
├── docker-compose.local.yml
└── README.md
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16.2.6 + React 19.2.6 + TypeScript 5.9.3 |
| 后端网关 | FastAPI（Python） |
| 向量数据库 | Weaviate 1.38.3（BM25 + HNSW） |
| 嵌入模型 | BAAI/bge-m3（FlagEmbedding，1024 维，CPU） |
| 文档解析 | Docling（PDF/DOCX）+ 自解析器（MD/代码） |
| 大语言模型 | llama-server（Gemma 4 31B Q4_K_M GGUF） |

## 快速开始

### 后端部署

在 WSL2 中运行：

```bash
# 启动 Weaviate
cd backend/stack
docker compose up -d

# 安装 Python 依赖
cd ../..
python -m venv backend/venv
source backend/venv/bin/activate
pip install fastapi uvicorn docling flag-embedding weaviate-client

# 启动 Gateway
python backend/rag_gateway.py
```

### 前端部署

```bash
cd frontend
npm install
npm run dev          # 开发模式（端口 3000）
npm run build        # 生产构建
npm start            # 生产模式
```

### 验证 UI

```bash
npm run verify:ui
```

## 端口说明

| 端口 | 服务 |
|------|------|
| 3000 | GUI 前端 |
| 8080 | Weaviate（通过 Docker 映射） |
| 9100 | RAG Gateway |
| 8000 | llama-server（推理服务） |

## 混合检索

Gateway `/v1/retrieve` 端点使用混合检索：
- **BM25**（GSE 中文分词）+ **HNSW 向量检索**（BGE-M3）
- `alpha` 参数控制权重（默认 0.55 偏向向量）
- 支持按 `scope` 过滤

## 增量索引

`batch_indexer.py` 基于 SHA-256 哈希的增量索引：
- 文件哈希不变则跳过
- 文件变化则删除旧切片后重新解析入库
- 状态保存在 `kb/.index_state.json`