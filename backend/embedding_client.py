#!/usr/bin/env python3
"""
Embedding Service HTTP Client
==============================
Shared by RAG Gateway (online) and Ingest Worker (batch) to call the
standalone CPU embedding service on port 9102.

Client-side TTLCache avoids redundant network calls for repeated queries.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EMBEDDING_URL = os.environ.get("RAG_EMBEDDING_URL", "http://127.0.0.1:9102")
CLIENT_TIMEOUT = float(os.environ.get("RAG_EMBEDDING_CLIENT_TIMEOUT", "30"))
CACHE_SIZE = int(os.environ.get("RAG_QUERY_VECTOR_CACHE_SIZE", "2048"))
CACHE_TTL = float(os.environ.get("RAG_QUERY_VECTOR_CACHE_TTL_SECONDS", "900"))


# ---------------------------------------------------------------------------
# Client-side TTL cache (L1 — reduces network hops)
# ---------------------------------------------------------------------------

_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str) -> list[float] | None:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        created_at, vec = entry
        if now - created_at >= CACHE_TTL:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return vec


def _cache_put(key: str, vec: list[float]) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), vec)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Metrics (client-side)
# ---------------------------------------------------------------------------

_metrics_lock = threading.Lock()
_metrics: dict[str, Any] = {
    "client_cache_hits": 0,
    "client_cache_misses": 0,
    "client_errors": 0,
    "client_total_ms": 0.0,
    "client_call_count": 0,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding service cannot be reached or returns an error."""


def encode(texts: list[str], priority: str = "high") -> list[list[float]]:
    """Encode one or more texts via the remote embedding service.

    Single-text requests use a client-side TTL cache.
    """
    if not texts:
        return []

    t0 = time.monotonic()
    # Client-side cache for single-text requests
    if len(texts) == 1:
        cached = _cache_get(texts[0])
        if cached is not None:
            with _metrics_lock:
                _metrics["client_cache_hits"] += 1
            return [cached]
        with _metrics_lock:
            _metrics["client_cache_misses"] += 1

    payload = json.dumps({"texts": texts, "priority": priority}).encode("utf-8")
    req = Request(
        f"{EMBEDDING_URL}/embed",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "embedding-client/1.0"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=CLIENT_TIMEOUT) as resp:
            body = resp.read(10 * 1024 * 1024)
        result = json.loads(body.decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        with _metrics_lock:
            _metrics["client_errors"] += 1
        raise EmbeddingServiceError(f"embedding service call failed: {type(exc).__name__}") from exc

    vectors: list[list[float]] = result.get("vectors", [])

    # Cache single results
    if len(texts) == 1 and vectors:
        _cache_put(texts[0], vectors[0])

    with _metrics_lock:
        _metrics["client_call_count"] += 1
        _metrics["client_total_ms"] += (time.monotonic() - t0) * 1000

    return vectors


def encode_one(text: str, priority: str = "high") -> list[float]:
    """Convenience: encode a single text and return its vector."""
    vecs = encode([text], priority=priority)
    if not vecs:
        raise EmbeddingServiceError("empty response from embedding service")
    return vecs[0]


def get_metrics() -> dict[str, Any]:
    with _metrics_lock:
        total = _metrics["client_cache_hits"] + _metrics["client_cache_misses"]
        hit_rate = _metrics["client_cache_hits"] / total if total > 0 else 0
        avg_ms = _metrics["client_total_ms"] / _metrics["client_call_count"] if _metrics["client_call_count"] > 0 else 0
        return {
            "client_cache_hit_rate": round(hit_rate, 4),
            "client_cache_hits": _metrics["client_cache_hits"],
            "client_cache_misses": _metrics["client_cache_misses"],
            "client_errors": _metrics["client_errors"],
            "client_avg_ms": round(avg_ms, 2),
            "client_call_count": _metrics["client_call_count"],
            "cache_size": len(_cache),
        }
