#!/usr/bin/env python3
"""Dependency-free reliability helpers for global RAG retrieval and MCP output."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable


DOCUMENT_LIBRARY_IDS = ("ai-work", "academic", "production", "notes")
SEARCH_MODES = ("fast", "auto", "deep")


class SearchValidationError(ValueError):
    """Raised when a model-provided search request is outside safe bounds."""


def normalize_query(value: str, max_chars: int = 500) -> str:
    query = re.sub(r"\s+", " ", str(value or "")).strip()
    if not query:
        raise SearchValidationError("query must not be empty")
    return query[:max_chars]


def validate_libraries(values: Iterable[str] | None) -> list[str]:
    if not values:
        return list(DOCUMENT_LIBRARY_IDS)
    result: list[str] = []
    for value in values:
        library_id = str(value).strip().lower()
        if library_id not in DOCUMENT_LIBRARY_IDS:
            raise SearchValidationError(f"unsupported document library: {library_id}")
        if library_id not in result:
            result.append(library_id)
    return result


def choose_alpha(query: str) -> float:
    """Prefer lexical recall for identifiers/errors and semantic recall for prose."""
    if re.search(r"(?:0x[0-9a-f]+|\b[A-Z_]{3,}\b|[/\\]|--[a-z0-9-]+|\w+\.\w+)", query, re.I):
        return 0.38
    if len(query) >= 48 or any(mark in query for mark in "为什么如何怎样是否请结合"):
        return 0.62
    return 0.52


def candidate_limit(mode: str, top_k: int) -> int:
    if mode not in SEARCH_MODES:
        raise SearchValidationError(f"unsupported search mode: {mode}")
    multiplier = {"fast": 1, "auto": 2, "deep": 3}[mode]
    return min(max(top_k * multiplier, top_k), 30)


def _evidence_key(item: dict[str, Any]) -> str:
    chunk_id = str(item.get("chunk_id") or "").strip()
    if chunk_id:
        return f"chunk:{chunk_id}"
    return "fallback:{document_id}:{page}:{content}".format(
        document_id=item.get("document_id", ""),
        page=item.get("page", 0),
        content=str(item.get("content", ""))[:160],
    )


def merge_library_results(
    result_sets: dict[str, list[dict[str, Any]]],
    top_k: int,
    rank_constant: int = 60,
) -> list[dict[str, Any]]:
    """Fuse independently ranked libraries without comparing backend-native scores."""
    fused: dict[str, dict[str, Any]] = {}
    for library_id, items in result_sets.items():
        for rank, raw in enumerate(items, start=1):
            key = _evidence_key(raw)
            entry = fused.setdefault(key, {"item": dict(raw), "score": 0.0, "libraries": []})
            entry["score"] += 1.0 / (rank_constant + rank)
            if library_id not in entry["libraries"]:
                entry["libraries"].append(library_id)
            entry["item"]["library_id"] = library_id
    ordered = sorted(fused.values(), key=lambda entry: (-entry["score"], _evidence_key(entry["item"])))
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(ordered[:top_k], start=1):
        item = entry["item"]
        item["evidence_id"] = f"E{index}"
        item["retrieval_score"] = round(entry["score"], 8)
        item["matched_libraries"] = entry["libraries"]
        results.append(item)
    return results


def compact_evidence(
    results: Iterable[dict[str, Any]],
    *,
    snippet_chars: int = 1200,
    total_chars: int = 12000,
) -> list[dict[str, Any]]:
    """Bound model-visible evidence and remove internal-only fields."""
    compact: list[dict[str, Any]] = []
    used = 0
    for raw in results:
        remaining = total_chars - used
        if remaining <= 0:
            break
        content = re.sub(r"\x00", "", str(raw.get("content") or "")).strip()
        content = content[: min(snippet_chars, remaining)]
        if not content:
            continue
        used += len(content)
        compact.append({
            "evidence_id": raw.get("evidence_id", f"E{len(compact) + 1}"),
            "library_id": raw.get("library_id", ""),
            "title": str(raw.get("title") or raw.get("source_name") or "未命名资料")[:240],
            "heading": str(raw.get("heading") or "")[:240],
            "source_path": str(raw.get("source_path") or "")[:1000],
            "page": int(raw.get("page") or 0),
            "document_id": str(raw.get("document_id") or ""),
            "version_id": str(raw.get("version_id") or ""),
            "content": content,
            "retrieval_score": raw.get("retrieval_score", raw.get("score", 0.0)),
        })
    return compact


class TTLCache:
    """Small thread-safe LRU/TTL cache used for query embeddings."""

    def __init__(self, max_size: int = 2048, ttl_seconds: float = 900.0):
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._values: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            created_at, value = entry
            if now - created_at >= self.ttl_seconds:
                self._values.pop(key, None)
                return None
            self._values.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = (time.monotonic(), value)
            self._values.move_to_end(key)
            while len(self._values) > self.max_size:
                self._values.popitem(last=False)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 15.0
    failures: int = 0
    opened_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            return self.failures < self.failure_threshold or current - self.opened_at >= self.recovery_seconds

    def success(self) -> None:
        with self._lock:
            self.failures = 0
            self.opened_at = 0.0

    def failure(self, now: float | None = None) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.monotonic() if now is None else now
