# LLM 问题改写与多查询融合实施说明

## 目标

在不改变默认检索行为的前提下，为复杂、模糊、跨术语问题提供可选的召回增强。用户必须在知识检索页手动开启“让智能助手扩展问法”，关闭时不会调用 LLM，也不会增加检索次数。

## 开源方案选择

本实现复用开源社区已经验证的基本组件，但不引入额外框架依赖：

- [Haystack QueryExpander](https://docs.haystack.deepset.ai/docs/queryexpander)：要求模型以 JSON 返回多个语义相近但互补的检索问法。
- [LlamaIndex Query Transformations](https://developers.llamaindex.ai/python/framework/optimizing/advanced_retrieval/query_transformations/)：在进入索引前对查询做显式转换。
- RAG-Fusion 的 Reciprocal Rank Fusion 思路：用各结果在不同查询中的排名融合，而不是直接比较不同检索批次的原始分数。

没有采用 HyDE 作为默认方案。HyDE 会先生成假设性答案，适合某些纯语义场景，但对错误码、版本、路径和命令等工程查询更容易产生偏移。

## 数据流

1. 前端默认关闭问题改写。
2. 用户显式开启后，请求 `/v1/retrieve` 时增加：

   ```json
   {
     "rewrite_enabled": true,
     "rewrite_max_variants": 2
   }
   ```

3. Gateway 调用 OpenAI 兼容模型，只生成两个短查询，不生成答案。
4. 原问题始终保留，并使用 `1.35` 的融合权重；每个扩展问法权重为 `1.0`。
5. 每个问法执行相同的 BGE-M3 + BM25 混合检索和相同的数据隔离过滤。
6. 使用加权 Reciprocal Rank Fusion 去重并重新排序，最后只返回用户要求的 `top_k`。
7. 响应中的 `rewrite` 字段向前端说明实际使用的问法、模型、是否应用以及降级原因。

## 面向未来的兼容边界

- **稳定请求协议**：前端只提交 `rewrite_enabled`、`rewrite_strategy` 和数量上限，不依赖具体厂商 SDK。
- **可替换模型提供方**：`llm_adapter.py` 当前使用 OpenAI 兼容协议，本地 llama.cpp、闭源 API 或未来代理服务只需适配这一层。
- **策略与检索解耦**：`retrieve_with_optional_rewrite()` 通过 `rewrite_call`、`search_call` 注入实现；将来增加 HyDE、Step-back、规则扩展、重排器或新向量库时，不必重写失败回退和融合逻辑。
- **版本化响应**：`rewrite.schema_version` 当前为 `1.0`；新增字段保持向后兼容，破坏性变化才升级主版本。
- **能力发现**：`GET /v1/rewrite/capabilities` 返回服务端支持的策略、提供方、上限和融合方式，未来前端可据此动态呈现新工具。
- **可观测但不泄露推理**：只返回实际查询、模型、Token 计数和降级原因，不存储或展示模型隐式思维过程。

## 安全与降级

- 原问题中的文件名、错误码、版本号、路径、命令和专有名词必须保留。
- 模型输出经过单行化、长度限制、大小写去重和数量上限校验。
- LLM 未配置、超时、HTTP 错误、JSON 无效或没有生成新问法时，自动使用原问题检索。
- 某个扩展问法检索失败时，只跳过该问法；原问题结果仍正常返回。
- 前端明确显示“已增强”或“已降级”，不会静默伪装成成功改写。
- 默认最多生成两个扩展问法，输出上限 320 Token，减少本地模型延迟和上下文消耗。

## 配置

问题改写与智能分类共用 `backend/llm_adapter.py` 的 OpenAI 兼容配置：

```env
LLM_API_BASE=http://127.0.0.1:8000/v1
LLM_API_KEY=
LLM_MODEL=gemma-4-31b-q4
```

本地 llama.cpp 服务允许留空 API Key。也可以在前端“系统设置 → 智能整理与问题改写”中填写。

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `RAG_QUERY_REWRITE_MAX_VARIANTS` | `2` | 服务端允许的最大扩展问法数，最高 4 |
| `RAG_QUERY_REWRITE_TIMEOUT_SECONDS` | `30` | LLM 改写超时 |
| `RAG_QUERY_REWRITE_RRF_K` | `60` | 倒数排名融合平滑常数 |

## 返回示例

```json
{
  "query": "Gemma 启动后显存不足",
  "rewrite": {
    "enabled": true,
    "applied": true,
    "schema_version": "1.0",
    "strategy": "multi_query",
    "provider": "openai_compatible",
    "method": "weighted_rrf",
    "queries": [
      "Gemma 启动后显存不足",
      "llama.cpp Gemma 启动 OOM 排查",
      "Gemma 模型显存占用过高解决方法"
    ],
    "model": "gemma-4-31b-q4",
    "fallback_reason": null
  },
  "results": []
}
```

## 关键文件

- `backend/query_rewriter.py`：输出清洗、去重、结果标识和加权排名融合。
- `backend/llm_adapter.py`：兼容本地/远程模型的问题改写调用。
- `backend/rag_gateway.py`：改写编排、多次检索、融合和自动降级。
- `backend/test_query_rewriter.py`：纯函数、成功编排、关闭状态和模型故障回退测试。
- `app/page.tsx`：显式开关、请求字段、增强/降级状态与实际问法展示。
