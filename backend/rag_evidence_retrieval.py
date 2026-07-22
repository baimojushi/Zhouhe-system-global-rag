#!/usr/bin/env python3
"""Document-fair, evidence-first layered retrieval for global RAG.

Architecture
────────────
  1. Per-document quota   – group candidates by document_id, cap at N per doc
  2. Dual-channel         – paper / monograph separate candidate paths
  3. Intent classifier    – lightweight rule-based query → source allocation
  4. Evidence reranker    – combine dense + lexical + evidence + source-fit
  5. Structured context   – primary_evidence / supporting_background split

Usage
─────
  from rag_evidence_retrieval import evidence_search
  result = evidence_search(query="...", research_mode="balanced")
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

log = logging.getLogger("evidence_retrieval")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_TYPE_PAPER = frozenset({"paper", "thesis", "standard", "report"})
SOURCE_TYPE_BOOK = frozenset({"book", "review", "textbook", "monograph"})

EVIDENCE_SECTIONS = frozenset({
    "abstract", "introduction", "methods", "methodology",
    "results", "findings", "discussion", "conclusion",
    "experiment", "evaluation", "analysis",
})

# Default quotas
MAX_CHUNKS_PER_DOC = 3          # global cap
MAX_CHUNKS_PER_SECTION = 2      # per-section cap
MAX_DOCS_FINAL = 3              # min distinct docs in final context
QUOTA_SOFT = True               # relax when insufficient candidates

# ---------------------------------------------------------------------------
# Intent classifier (rule-based, no LLM call)
# ---------------------------------------------------------------------------

# Keywords that suggest specific intent categories
_INTENT_PATTERNS: list[tuple[str, str, dict]] = [
    # (intent, description, source_weights)
    ("empirical_evidence", "实验证据、数据、方法、结论",
     {"paper": 0.7, "review": 0.2, "book": 0.1}),
    ("concept_definition", "概念定义、术语解释、理论介绍",
     {"book": 0.6, "review": 0.3, "paper": 0.1}),
    ("method_survey", "方法综述、技术路线、主流方案",
     {"paper": 0.5, "review": 0.3, "book": 0.2}),
    ("recent_progress", "近五年进展、最新研究、前沿",
     {"paper": 0.7, "review": 0.2, "book": 0.1}),
    ("historical_context", "历史来源、理论脉络、经典",
     {"book": 0.5, "paper": 0.3, "review": 0.2}),
    ("specific_source", "指定文献、某作者观点、引用",
     {"book": 0.4, "paper": 0.4, "review": 0.2}),
]

_EMPIRICAL_WORDS = frozenset({
    "实验", "数据", "结果", "方法", "样本", "试验", "检测",
    "实验证明", "evidence", "experiment", "data", "result",
    "method", "finding", "significant", "p-value", "accuracy",
})
_CONCEPT_WORDS = frozenset({
    "定义", "概念", "什么是", "含义", "解释", "理论", "原理",
    "definition", "concept", "meaning", "theory",
})
_METHOD_WORDS = frozenset({
    "方法", "技术", "方案", "approach", "method", "technique",
    "framework", "pipeline", "workflow",
})
_RECENT_WORDS = frozenset({
    "最新", "近期", "近年", "近年", "进展", "前沿", "趋势",
    "recent", "latest", "state of the art", "SOTA",
})
_HISTORICAL_WORDS = frozenset({
    "历史", "起源", "传统", "经典", "来源", "脉络", "演变",
    "history", "origin", "classic", "tradition",
})
_SPECIFIC_WORDS = frozenset({
    "认为", "指出", "提出", "观点", "著作", "书中",
    "argues", "states", "according to", "in his book",
})


def classify_intent(query: str) -> dict[str, Any]:
    """Classify query intent and return preferred source weights.

    Returns dict with intent, preferred_sources, description.
    Falls back to balanced mode when no clear intent is detected.
    """
    q = query.lower()

    # Score each intent category
    scores: dict[str, float] = {}
    for word_set, intent, weight_key in [
        (_EMPIRICAL_WORDS, "empirical_evidence", "empirical_evidence"),
        (_CONCEPT_WORDS, "concept_definition", "concept_definition"),
        (_METHOD_WORDS, "method_survey", "method_survey"),
        (_RECENT_WORDS, "recent_progress", "recent_progress"),
        (_HISTORICAL_WORDS, "historical_context", "historical_context"),
        (_SPECIFIC_WORDS, "specific_source", "specific_source"),
    ]:
        match_count = sum(1 for w in word_set if w in q)
        if match_count > 0:
            scores[intent] = scores.get(intent, 0) + match_count

    if not scores:
        # Balanced default
        return {
            "intent": "balanced",
            "description": "均衡模式",
            "preferred_sources": {"paper": 0.4, "review": 0.3, "book": 0.3},
        }

    best_intent = max(scores, key=scores.get)
    for intent_name, desc, weights in _INTENT_PATTERNS:
        if intent_name == best_intent:
            return {
                "intent": intent_name,
                "description": desc,
                "preferred_sources": weights,
            }

    return {
        "intent": "balanced",
        "description": "均衡模式",
        "preferred_sources": {"paper": 0.4, "review": 0.3, "book": 0.3},
    }


# ---------------------------------------------------------------------------
# Per-document aggregation & quota
# ---------------------------------------------------------------------------

def _detect_source_type(item: dict[str, Any]) -> str:
    """Detect source_type from item properties. Defaults to 'paper' if unclear."""
    source_type = str(item.get("source_type", "") or "").strip().lower()
    if source_type:
        return source_type
    # Fallback: infer from mime_type or source_path
    mime = str(item.get("mime_type", "") or "").lower()
    if "pdf" in mime:
        return "paper"  # safe default for PDFs
    return "paper"


def _detect_section_type(item: dict[str, Any]) -> str:
    """Detect section type from heading or content."""
    heading = str(item.get("heading", "") or "").lower().strip()
    content = str(item.get("content", "") or "").lower()[:200]
    combined = f"{heading} {content}"
    for section in EVIDENCE_SECTIONS:
        if section in combined:
            return section
    return "general"


def apply_document_quota(
    candidates: list[dict[str, Any]],
    max_per_doc: int = MAX_CHUNKS_PER_DOC,
    max_per_section: int = MAX_CHUNKS_PER_SECTION,
    soft: bool = QUOTA_SOFT,
) -> list[dict[str, Any]]:
    """Group candidates by document_id and cap per-doc / per-section counts.

    Within each document, higher-scoring chunks are kept.
    Returns a re-ordered list respecting original rank order.
    """
    # Group by document_id
    doc_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    doc_order: list[str] = []
    for item in candidates:
        doc_id = str(item.get("document_id", item.get("source_hash", "")) or "")
        if not doc_id:
            doc_id = f"orphan-{hash(str(item.get('source_path', ''))[:16])}"
        if doc_id not in doc_groups:
            doc_order.append(doc_id)
        doc_groups[doc_id].append(item)

    # Apply per-doc cap (keep highest scored)
    selected: list[dict[str, Any]] = []
    for doc_id in doc_order:
        items = doc_groups[doc_id]
        # Sort by score descending
        items.sort(key=lambda x: -(x.get("retrieval_score", x.get("score", 0))))
        # Apply section cap
        section_counts: dict[str, int] = defaultdict(int)
        for item in items:
            section = _detect_section_type(item)
            if section_counts[section] >= max_per_section:
                continue
            section_counts[section] += 1
            selected.append(item)
            # Stop if we've hit the per-doc limit
            if len([s for s in selected if str(s.get("document_id", s.get("source_hash", "")) or "") == doc_id]) >= max_per_doc:
                break

    # Sort back by original rank order (preserve retrieval score order)
    selected.sort(key=lambda x: -(x.get("retrieval_score", x.get("score", 0))))

    # Soft constraint: if not enough distinct documents, relax quota
    if soft:
        distinct_docs = set()
        for item in selected:
            doc_id = str(item.get("document_id", item.get("source_hash", "")) or "")
            if doc_id:
                distinct_docs.add(doc_id)
        if len(distinct_docs) < MAX_DOCS_FINAL and len(candidates) > len(selected):
            # Allow more chunks from top documents to fill gap
            remaining = [c for c in candidates if c not in selected]
            for item in remaining[:MAX_DOCS_FINAL - len(distinct_docs)]:
                selected.append(item)

    return selected


# ---------------------------------------------------------------------------
# Dual-channel candidate assembly
# ---------------------------------------------------------------------------

@dataclass
class ChannelResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    channel: str = "paper"


def assemble_dual_channel(
    candidates: list[dict[str, Any]],
    preferred_sources: dict[str, float],
) -> list[dict[str, Any]]:
    """Split candidates into paper/book channels, allocate slots per weights.

    Returns an interleaved list respecting the target source ratio.
    """
    # Classify each candidate
    paper_items: list[dict[str, Any]] = []
    book_items: list[dict[str, Any]] = []
    for item in candidates:
        st = _detect_source_type(item)
        if st in SOURCE_TYPE_BOOK:
            book_items.append(item)
        else:
            paper_items.append(item)

    # Allocate slots
    total_weight = sum(preferred_sources.get(k, 0) for k in ("paper", "review", "book"))
    if total_weight <= 0:
        return candidates

    paper_ratio = (preferred_sources.get("paper", 0) + preferred_sources.get("review", 0)) / total_weight
    book_ratio = preferred_sources.get("book", 0) / total_weight

    total_slots = len(candidates)
    paper_slots = max(1, int(total_slots * paper_ratio))
    book_slots = max(1, int(total_slots * book_ratio))

    # Interleave: take from paper and book alternately
    result: list[dict[str, Any]] = []
    pi, bi = 0, 0
    turn = 0  # 0 = paper, 1 = book
    while len(result) < total_slots:
        if turn == 0 and pi < len(paper_items) and len([x for x in result if x in paper_items]) < paper_slots:
            result.append(paper_items[pi])
            pi += 1
        elif bi < len(book_items) and len([x for x in result if x in book_items]) < book_slots:
            result.append(book_items[bi])
            bi += 1
        elif pi < len(paper_items):
            result.append(paper_items[pi])
            pi += 1
        elif bi < len(book_items):
            result.append(book_items[bi])
            bi += 1
        else:
            break
        turn = 1 - turn

    return result


# ---------------------------------------------------------------------------
# Evidence reranker
# ---------------------------------------------------------------------------

def _evidence_score(item: dict[str, Any]) -> float:
    """Compute evidence quality score (0-1) for a single chunk."""
    content = str(item.get("content", "") or "")
    heading = str(item.get("heading", "") or "").lower()
    source_type = _detect_source_type(item)
    section = _detect_section_type(item)

    score = 0.0

    # 1. Dense retrieval score (already normalized 0-1-ish)
    dense = float(item.get("retrieval_score", item.get("score", 0)))
    score += 0.25 * min(dense, 1.0)

    # 2. Evidence section bonus
    if section in ("results", "conclusion", "findings", "experiment"):
        score += 0.20
    elif section in ("methods", "methodology", "analysis", "evaluation"):
        score += 0.15
    elif section in ("abstract", "introduction", "discussion"):
        score += 0.10

    # 3. Empirical keywords in content
    empirical_hits = sum(1 for w in _EMPIRICAL_WORDS if w in content.lower())
    if empirical_hits >= 3:
        score += 0.15
    elif empirical_hits >= 1:
        score += 0.08

    # 4. Tables, figures, formulas
    if re.search(r"table|图\d|table\s+\d|fig\.|公式\(|equation", content.lower()):
        score += 0.10

    # 5. Source fit (prefer paper for evidence, book for background)
    if source_type in SOURCE_TYPE_PAPER and section in ("results", "conclusion", "experiment"):
        score += 0.10
    elif source_type in SOURCE_TYPE_BOOK and section in ("introduction", "general"):
        score += 0.05

    # 6. Penalty for redundant/buzzword-heavy content
    buzzwords = ["in recent years", "with the development", "this paper proposes", "综上所述"]
    bw_hits = sum(1 for bw in buzzwords if bw in content.lower())
    score -= 0.03 * bw_hits

    return max(0.0, min(1.0, score))


def rerank_by_evidence(
    candidates: list[dict[str, Any]],
    diversity_penalty: float = 0.10,
) -> list[dict[str, Any]]:
    """Rerank candidates combining retrieval score + evidence score + diversity.

    Uses MMR-like diversity: penalize items from the same document
    that are too similar to already-selected items.
    """
    if not candidates:
        return []

    scored: list[tuple[float, int, dict]] = []  # (final_score, -original_idx, item)
    seen_docs: set[str] = set()

    for idx, item in enumerate(candidates):
        ev_score = _evidence_score(item)
        dense = float(item.get("retrieval_score", item.get("score", 0)))
        # Final score = dense + evidence - diversity penalty
        final = 0.45 * min(dense, 1.0) + 0.55 * ev_score

        # Diversity: penalize items from already-represented docs
        doc_id = str(item.get("document_id", item.get("source_hash", "")) or "")
        if doc_id and doc_id in seen_docs:
            final -= diversity_penalty
        else:
            seen_docs.add(doc_id)

        scored.append((final, -idx, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, _, item in scored]


# ---------------------------------------------------------------------------
# MMR deduplication
# ---------------------------------------------------------------------------

def _content_overlap(a: str, b: str) -> float:
    """Simple character n-gram overlap (0-1)."""
    def ngrams(s: str, n: int = 3) -> set[str]:
        return {s[i:i+n] for i in range(len(s) - n + 1)}
    if not a or not b:
        return 0.0
    ag = ngrams(a.lower())
    bg = ngrams(b.lower())
    if not ag or not bg:
        return 0.0
    return len(ag & bg) / min(len(ag), len(bg))


def mmr_dedup(
    candidates: list[dict[str, Any]],
    top_k: int = 12,
    lambda_param: float = 0.6,
    max_per_doc: int = 3,
) -> list[dict[str, Any]]:
    """Maximum Marginal Relevance to reduce redundancy."""
    if not candidates:
        return []

    selected: list[dict[str, Any]] = []
    remaining = list(candidates)
    doc_counts: dict[str, int] = defaultdict(int)

    while len(selected) < top_k and remaining:
        best_idx = -1
        best_score = -float("inf")

        for i, item in enumerate(remaining):
            doc_id = str(item.get("document_id", item.get("source_hash", "")) or "")
            # Doc quota check
            if doc_id and doc_counts.get(doc_id, 0) >= max_per_doc:
                continue

            relevance = float(item.get("retrieval_score", item.get("score", 0)))
            # Diversity: max similarity to already selected
            max_sim = 0.0
            for sel in selected:
                sim = _content_overlap(
                    str(item.get("content", "")),
                    str(sel.get("content", "")),
                )
                max_sim = max(max_sim, sim)

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        if best_idx < 0:
            break
        item = remaining.pop(best_idx)
        doc_id = str(item.get("document_id", item.get("source_hash", "")) or "")
        doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
        selected.append(item)

    return selected


# ---------------------------------------------------------------------------
# Structured context builder
# ---------------------------------------------------------------------------

def build_structured_context(
    candidates: list[dict[str, Any]],
    intent: dict[str, Any],
    max_primary: int = 5,
    max_background: int = 5,
) -> dict[str, Any]:
    """Split final candidates into primary_evidence and supporting_background.

    Primary evidence: high-evidence-score items from paper/thesis sources.
    Supporting background: conceptual/definition items from book/review sources.
    """
    primary: list[dict] = []
    background: list[dict] = []

    ev_scores = [(i, _evidence_score(c)) for i, c in enumerate(candidates)]
    ev_scores.sort(key=lambda x: -x[1])

    for idx, score in ev_scores:
        item = candidates[idx]
        source_type = _detect_source_type(item)
        section = _detect_section_type(item)

        entry = {
            "evidence_id": item.get("evidence_id", f"E{len(primary) + len(background) + 1}"),
            "title": str(item.get("title", item.get("source_name", "")))[:240],
            "heading": str(item.get("heading", ""))[:240],
            "source_path": str(item.get("source_path", ""))[:1000],
            "page": int(item.get("page", 0)),
            "source_type": source_type,
            "section_type": section,
            "content": str(item.get("content", ""))[:2000],
            "evidence_score": round(score, 4),
        }

        # Classify as primary or background
        is_primary = (
            (source_type in SOURCE_TYPE_PAPER or source_type == "review")
            and section in ("results", "conclusion", "findings", "experiment",
                            "methods", "analysis", "evaluation")
            and score >= 0.15
        )
        is_primary = is_primary or (
            source_type in SOURCE_TYPE_PAPER
            and score >= 0.25
        )

        if is_primary and len(primary) < max_primary:
            entry["role"] = "primary_evidence"
            primary.append(entry)
        elif len(background) < max_background:
            entry["role"] = "supporting_background"
            background.append(entry)

    return {
        "intent": intent,
        "primary_evidence": primary,
        "supporting_background": background,
        "total_primary": len(primary),
        "total_background": len(background),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evidence_search(
    query: str,
    search_fn: Callable[[str, int, Optional[dict]], list[dict]],
    top_k: int = 12,
    research_mode: str = "balanced",
    alpha: Optional[float] = None,
    filters: Optional[dict] = None,
) -> dict[str, Any]:
    """Full evidence-aware retrieval pipeline.

    Args:
        query: Search query
        search_fn: Function with signature (query, top_k, filters) -> list[dict]
        top_k: Target number of final results
        research_mode: "balanced", "evidence", "fast"
        alpha: Optional hybrid search alpha
        filters: Optional Weaviate filters

    Returns structured context with primary_evidence and supporting_background.
    """
    # Step 0: Intent classification
    intent = classify_intent(query)

    # Step 1: Dual-channel candidate recall
    # Recall more candidates to have room for filtering
    recall_multiplier = 4 if research_mode == "evidence" else 3
    candidate_count = max(20, top_k * recall_multiplier)

    candidates = search_fn(query, candidate_count, filters)

    if not candidates:
        return {
            "intent": intent,
            "primary_evidence": [],
            "supporting_background": [],
            "total_primary": 0,
            "total_background": 0,
            "query": query,
        }

    # Step 2: Apply per-document quota
    quoted = apply_document_quota(candidates)

    # Step 3: Dual-channel assembly by source type
    mixed = assemble_dual_channel(quoted, intent.get("preferred_sources", {}))

    # Step 4: Evidence reranking
    reranked = rerank_by_evidence(mixed)

    # Step 5: MMR dedup
    deduped = mmr_dedup(reranked, top_k=top_k)

    # Step 6: Build structured context
    context = build_structured_context(deduped, intent)

    context["query"] = query
    context["research_mode"] = research_mode
    context["candidates_recalled"] = len(candidates)
    context["candidates_after_quota"] = len(quoted)
    context["candidates_final"] = len(deduped)

    return context
