# RAG 系统架构

## 检索增强生成

检索增强生成（RAG）系统由以下核心组件组成：

### 1. 向量数据库

Weaviate 提供混合检索能力，结合：

- **BM25 倒排索引**：基于关键词的精确匹配
- **HNSW 稠密向量检索**：基于语义相似度的向量搜索

#### 中文分词

Weaviate 的 GSE（General Segmentation Engine）插件支持中文分词：

```bash
# GSE 配置示例
"gemini": {
    "text2vec-contextionary": {
        "vectorizerModules": [
            "text2vec-contextionary"
        ]
    }
}
```

### 2. 嵌入模型

BGE-M3 是多语言嵌入模型：

- **维度**：1024 维
- **语言支持**：中、英、日、韩等多语言
- **最大上下文**：8192 tokens
- **量化**：INT4 量化后可降至 4 倍大小

#### 使用 FlagEmbedding 加载

```python
from FlagEmbedding import FlagModel

model = FlagModel("BAAI/bge-m3", cpu="CPU", use_fp16=False)
embedding = model.encode("这是一条测试文本")
print(f"向量维度: {len(embedding)}")  # 1024
```

### 3. 应用网关

RAG Gateway 负责：

- 用户查询的预处理
- 向量化（调用嵌入模型）
- 混合检索（BM25 + HNSW）
- 结果排序和融合
- 上下文组装
- 调用大语言模型生成回答

### 4. 文件知识库

支持的文件格式：

| 格式 | 解析器 | 备注 |
|------|--------|------|
| PDF | Docling | 支持扫描件 OCR |
| DOCX | Docling | 微软 Word |
| PPTX | Docling | 微软 PowerPoint |
| XLSX | Docling | 微软 Excel |
| Markdown | 自解析 | 按标题层级切片 |
| 代码 | 自解析 | 按函数/类边界切片 |

### 5. 增量索引

基于 SHA-256 哈希的增量索引机制：

1. 计算文件 SHA-256 哈希
2. 哈希值不变则跳过
3. 哈希值变化则重新解析和切片
4. 使用 UUIDv5 生成确定性 chunk_id
5. 批量写入新切片后删除旧切片

## 系统架构总览

```
用户查询 → RAG Gateway → 预处理 → 向量化
                                    ↓
                    ┌───────────────┴───────────────┐
                    ↓                               ↓
              BM25 检索                         HNSW 检索
                    \                               /
                     ────── 结果排序融合 ──────────
                                    ↓
                              上下文组装
                                    ↓
                              LLM 生成回答
```