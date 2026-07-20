#!/usr/bin/env python3
"""Pure helpers for LLM query expansion and reciprocal-rank fusion.

The implementation deliberately has no framework dependency.  It follows the
same small building blocks used by Haystack QueryExpander and RAG-Fusion:
generate a bounded set of alternative queries, always retain the original,
then fuse ranked result lists instead of trusting model-generated scores.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Awaitable, Callable, Iterable, Optional


MAX_QUERY_CHARS = 500


def normalize_query(value: Any) -> str:
    """Return a single-line, length-bounded query."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:MAX_QUERY_CHARS]


def extract_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating common Markdown code fences."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型没有返回可识别的 JSON")
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("模型返回的 JSON 格式无效") from exc
    if not isinstance(parsed, dict):
        raise ValueError("模型返回内容必须是 JSON 对象")
    return parsed


def sanitize_rewrite_candidates(
    original_query: str,
    candidates: Iterable[Any],
    max_variants: int = 2,
) -> list[str]:
    """Normalize, deduplicate and cap model-generated query variants."""
    original = normalize_query(original_query)
    seen = {original.casefold()} if original else set()
    variants: list[str] = []
    for candidate in candidates:
        value = normalize_query(candidate)
        identity = value.casefold()
        if not value or identity in seen:
            continue
        seen.add(identity)
        variants.append(value)
        if len(variants) >= max(0, max_variants):
            break
    return variants


def result_identity(item: dict[str, Any]) -> str:
    """Build a stable identity for deduplicating chunks across query runs."""
    for key in ("chunk_id", "id"):
        value = item.get(key)
        if value:
            return f"{key}:{value}"
    raw = "|".join(str(item.get(key, "")) for key in (
        "document_id", "version_id", "source_path", "page", "heading", "content"
    ))
    return "fallback:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reciprocal_rank_fusion(
    ranked_runs: list[tuple[str, list[dict[str, Any]], float]],
    top_k: int,
    rank_constant: int = 60,
) -> list[dict[str, Any]]:
    """Fuse result lists with weighted reciprocal rank fusion.

    Each run is ``(query, results, weight)``.  Scores are derived only from
    rank positions, which makes fusion robust across retrievers whose native
    score scales are not comparable.
    """
    if top_k <= 0 or not ranked_runs:
        return []
    constant = max(1, rank_constant)
    total_weight = sum(max(0.0, weight) for _, _, weight in ranked_runs) or 1.0
    best_possible = total_weight / (constant + 1)
    fused: dict[str, dict[str, Any]] = {}

    for query, results, weight in ranked_runs:
        safe_weight = max(0.0, weight)
        seen_in_run: set[str] = set()
        for rank, source in enumerate(results, start=1):
            identity = result_identity(source)
            if identity in seen_in_run:
                continue
            seen_in_run.add(identity)
            if identity not in fused:
                fused[identity] = {
                    "item": dict(source),
                    "fusion_score": 0.0,
                    "matched_queries": [],
                }
            entry = fused[identity]
            entry["fusion_score"] += safe_weight / (constant + rank)
            if query not in entry["matched_queries"]:
                entry["matched_queries"].append(query)

    ordered = sorted(
        fused.values(),
        key=lambda entry: (-entry["fusion_score"], result_identity(entry["item"])),
    )[:top_k]
    output: list[dict[str, Any]] = []
    for entry in ordered:
        item = dict(entry["item"])
        raw_score = float(entry["fusion_score"])
        item["fusion_score"] = round(raw_score, 8)
        item["score"] = round(min(1.0, raw_score / best_possible), 6)
        item["matched_queries"] = list(entry["matched_queries"])
        output.append(item)
    return output


async def retrieve_with_optional_rewrite(
    original_query: str,
    top_k: int,
    rewrite_enabled: bool,
    max_variants: int,
    rewrite_call: Callable[[str, int], Awaitable[dict[str, Any]]],
    search_call: Callable[[str, int], list[dict[str, Any]]],
    rank_constant: int = 60,
    strategy: str = "multi_query",
    provider: str = "openai_compatible",
    warning: Optional[Callable[[str], None]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Orchestrate expansion while guaranteeing original-query fallback."""
    query = normalize_query(original_query)
    metadata: dict[str, Any] = {
        "enabled": rewrite_enabled,
        "applied": False,
        "schema_version": "1.0",
        "strategy": strategy,
        "provider": provider,
        "method": "weighted_rrf",
        "queries": [query],
        "model": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "fallback_reason": None,
    }
    variants: list[str] = []
    if rewrite_enabled:
        try:
            expanded = await rewrite_call(query, max_variants)
            variants = sanitize_rewrite_candidates(
                query,
                expanded.get("queries", []),
                max_variants=max_variants,
            )
            metadata.update({
                "queries": [query, *variants],
                "model": expanded.get("model"),
                "prompt_tokens": int(expanded.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(expanded.get("completion_tokens", 0) or 0),
            })
            if not variants:
                metadata["fallback_reason"] = "模型没有生成有效的新问法，已使用原问题检索"
        except Exception as exc:
            if warning:
                warning(f"Query rewrite unavailable; falling back to original query: {exc}")
            metadata["fallback_reason"] = "问题改写暂时不可用，已使用原问题检索"

    per_query_k = min(20, max(top_k * 2, 10)) if variants else top_k
    original_results = search_call(query, per_query_k)
    ranked_runs: list[tuple[str, list[dict[str, Any]], float]] = [
        (query, original_results, 1.35),
    ]
    failed_variants = 0
    for variant in variants:
        try:
            ranked_runs.append((variant, search_call(variant, per_query_k), 1.0))
        except Exception as exc:
            failed_variants += 1
            if warning:
                warning(f"Expanded query retrieval failed; query skipped: {exc}")

    if len(ranked_runs) > 1:
        results = reciprocal_rank_fusion(
            ranked_runs,
            top_k=top_k,
            rank_constant=max(1, min(rank_constant, 1000)),
        )
        metadata["applied"] = True
        if failed_variants:
            metadata["fallback_reason"] = f"有 {failed_variants} 个扩展问法检索失败，其余结果已正常合并"
        return results, metadata

    if variants and failed_variants == len(variants):
        metadata["fallback_reason"] = "扩展问法检索失败，已使用原问题结果"
    return original_results[:top_k], metadata
