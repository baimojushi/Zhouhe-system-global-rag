#!/usr/bin/env python3
"""
LLM Adapter — OpenAI-compatible classification and query-rewrite endpoint.

Configuration (environment variables):
  LLM_API_BASE     — e.g. https://api.openai.com/v1  or  https://dashscope.aliyuncs.com/compatible-mode/v1
  LLM_API_KEY      — API key
  LLM_MODEL        — e.g. gpt-4o-mini, qwen-plus, qwen-turbo

Usage:
  # Called internally by rag_gateway.py
  from llm_adapter import call_llm_for_classification
  result = await call_llm_for_classification(library_id, subtree_json, routing_cards)
"""
import os
import json
import asyncio
from typing import Any

try:
    from query_rewriter import extract_json_object, sanitize_rewrite_candidates
except ImportError:
    from backend.query_rewriter import extract_json_object, sanitize_rewrite_candidates

_default_base = os.environ.get("LLM_API_BASE", "")
_default_key = os.environ.get("LLM_API_KEY", "")
_default_model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# Runtime-configurable overrides (set via /v1/llm/config)
_runtime_base: str = ""
_runtime_key: str = ""
_runtime_model: str = ""


def _base() -> str:
    return _runtime_base or _default_base


def _key() -> str:
    return _runtime_key or _default_key


def _model() -> str:
    return _runtime_model or _default_model


def update_config(base: str = "", key: str = "", model: str = ""):
    """Update LLM configuration at runtime (called from /v1/llm/config)."""
    global _runtime_base, _runtime_key, _runtime_model
    if base:
        _runtime_base = base
    if key:
        _runtime_key = key
    if model:
        _runtime_model = model


def get_config() -> dict:
    """Return current LLM configuration (key masked)."""
    base = _base()
    key = _key()
    model = _model()
    masked_key = (key[:6] + "****" + key[-4:]) if len(key) > 10 else ("****" if key else "")
    return {
        "llm_api_base": base or "(未配置)",
        "llm_api_key": masked_key or "(未配置)",
        "llm_model": model,
        "configured": bool(base),
    }


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _key():
        headers["Authorization"] = f"Bearer {_key()}"
    return headers

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
你是一个知识库分类助手。请根据提供的目录结构和路由卡，将未归类文件分配到最合适的目录节点。

## 目录结构
{subtree}

## 待分类文件（路由卡）
{routing_cards}

## 分类规则
1. 根据文件的标题、信号（signals）和摘要，判断它应该属于哪个 node_id。
2. 只返回 JSON，不要包含其他文字。
3. 每个文件必须给出 move 或 hold 决策。
4. confidence 范围 0.0–1.0。

## 返回 JSON 格式
{{
  "operations": [
    {{
      "op": "move",
      "file_id": "file-xxx",
      "target_node_id": "pr-incidents",
      "confidence": 0.96,
      "reason_code": "SIGNAL_MATCH"
    }}
  ],
  "holds": [
    {{
      "file_id": "file-yyy",
      "confidence": 0.54,
      "reason_code": "AMBIGUOUS_SIBLINGS"
    }}
  ]
}}

只返回 JSON。
"""

_QUERY_REWRITE_PROMPT = """\
你是知识检索中的“问题扩展器”，不是回答助手。请把用户问题改写成最多 {max_variants} 个互补的检索问法，以扩大召回范围。

规则：
1. 保留原意，不回答问题，不捏造事实。
2. 文件名、路径、命令、错误码、产品名、型号、版本号和专有名词必须原样保留。
3. 一个问法补充可能的中文同义表述；另一个可补充常见英文技术词或更明确的故障现象。
4. 每个问法应能单独用于搜索；不要重复原问题。
5. 只返回 JSON：{{"queries":["问法一","问法二"]}}。

用户问题：{query}
"""


async def call_llm_for_classification(
    library_id: str,
    subtree: str,
    routing_cards: list[dict],
) -> dict[str, Any]:
    """Call OpenAI-compatible LLM API for classification.

    Returns dict with keys: taxonomy_version, operations, holds, model_provider,
    prompt_tokens, completion_tokens.
    """
    import aiohttp

    if not _base():
        raise ValueError("LLM 未配置：请在前端设置页面配置模型服务地址")

    prompt = _CLASSIFY_PROMPT.format(subtree=subtree, routing_cards=json.dumps(routing_cards, ensure_ascii=False, indent=2))

    async with aiohttp.ClientSession() as session:
        headers = _headers()
        payload = {
            "model": _model(),
            "messages": [
                {"role": "system", "content": "你是知识库分类助手。只返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
        }

        # Respect the runtime-configured provider.  Using _default_base here
        # silently ignored changes made after process start.
        url = f"{_base().rstrip('/')}/chat/completions"
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {text[:200]}")

            data = await resp.json()

    # Parse response
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM returned no choices")

    content = choices[0].get("message", {}).get("content", "{}")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError(f"LLM response not valid JSON: {content[:200]}")

    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    return {
        "taxonomy_version": 1,
        "operations": parsed.get("operations", []),
        "holds": parsed.get("holds", []),
        "model_provider": _model().split("-")[0] if "-" in _model() else _model(),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


async def call_llm_for_query_rewrite(
    query: str,
    max_variants: int = 2,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Generate bounded alternatives through any OpenAI-compatible endpoint."""
    import aiohttp

    if not _base():
        raise ValueError("模型服务地址未配置")
    max_variants = max(1, min(int(max_variants), 4))
    prompt = _QUERY_REWRITE_PROMPT.format(query=query, max_variants=max_variants)
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": "你只扩展检索问法，并严格返回 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 320,
        "response_format": {"type": "json_object"},
    }
    url = f"{_base().rstrip('/')}/chat/completions"
    timeout = aiohttp.ClientTimeout(total=max(3, min(int(timeout_seconds), 120)))
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers(), timeout=timeout) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"模型服务返回 HTTP {resp.status}: {text[:200]}")
            data = await resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("模型没有返回改写结果")
    content = choices[0].get("message", {}).get("content", "")
    parsed = extract_json_object(content)
    variants = sanitize_rewrite_candidates(query, parsed.get("queries", []), max_variants)
    usage = data.get("usage", {})
    return {
        "queries": variants,
        "model": data.get("model") or _model(),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
    }


async def test_connectivity() -> dict:
    """Send a minimal request to the LLM API to verify connectivity.

    Returns dict with ok, latency_ms, model, error fields.
    """
    import aiohttp
    import time

    base = _base()
    key = _key()
    model = _model()

    if not base:
        return {"ok": False, "error": "模型服务地址未配置", "model": model}

    models_url = f"{base.rstrip('/')}/models"
    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            headers = _headers()
            async with session.get(models_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                latency_ms = int((time.time() - start) * 1000)
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])]
                    model_ok = not model or any(model in m for m in models)
                    return {
                        "ok": True,
                        "latency_ms": latency_ms,
                        "model": model,
                        "model_found": model_ok,
                        "available_models": models[:10],
                    }
                else:
                    text = await resp.text()
                    return {"ok": False, "error": f"HTTP {resp.status}: {text[:120]}", "model": model, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {"ok": False, "error": str(e)[:200], "model": model, "latency_ms": latency_ms}
