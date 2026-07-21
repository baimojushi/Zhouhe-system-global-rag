#!/usr/bin/env python3
"""
Standalone CPU Embedding Service
================================
Single BGE-M3 instance shared by Gateway (online queries) and
Ingest Worker (batch indexing). Dual priority queue:
high (online) always drained before low (ingest).

Port: 9102 (configurable via RAG_EMBEDDING_PORT)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/opt/global-rag/cache/huggingface")
os.environ.setdefault("DOCLING_ARTIFACTS_PATH", "/opt/global-rag/cache/docling-models")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from FlagEmbedding import FlagModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("RAG_EMBEDDING_PORT", "9102"))
LOG_FILE = Path("/opt/global-rag/logs/embedding-service.log")
CACHE_SIZE = int(os.environ.get("RAG_QUERY_VECTOR_CACHE_SIZE", "2048"))
CACHE_TTL = float(os.environ.get("RAG_QUERY_VECTOR_CACHE_TTL_SECONDS", "900"))
MAX_BATCH = int(os.environ.get("RAG_EMBEDDING_MAX_BATCH", "128"))

os.makedirs(LOG_FILE.parent, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("embedding_service")

# ---------------------------------------------------------------------------
# Model (lazy, thread-safe via background worker)
# ---------------------------------------------------------------------------

_model: FlagModel | None = None
_model_init_lock = threading.Lock()


def _init_model() -> FlagModel:
    global _model
    if _model is None:
        with _model_init_lock:
            if _model is None:
                log.info("Loading BGE-M3 model...")
                _model = FlagModel("BAAI/bge-m3", cpu="CPU", use_fp16=False)
                log.info("BGE-M3 loaded OK")
    return _model


# ---------------------------------------------------------------------------
# Embedding cache (on the server side)
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
# Priority queue — background worker threads drain high-prio before low-prio
# ---------------------------------------------------------------------------

# (priority, texts, result_dict)
# priority=0 → online queries, priority=1 → ingest
_encode_queue: queue.PriorityQueue = queue.PriorityQueue()

# Metrics counters (thread-safe via lock)
_metrics_lock = threading.Lock()
_metrics: dict[str, Any] = {
    "encode_count": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_encode_ms": 0.0,
    "batches_high": 0,
    "batches_low": 0,
    "queue_high_depth": 0,
    "queue_low_depth": 0,
    "errors": 0,
}


def _encode_worker() -> None:
    """Background thread: drain high-priority queue first, then low-priority."""
    model = _init_model()
    while True:
        try:
            priority, texts, result = _encode_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        t0 = time.monotonic()
        try:
            vectors = model.encode(texts).tolist()
            result["vectors"] = vectors
            result["latency_ms"] = (time.monotonic() - t0) * 1000
            with _metrics_lock:
                _metrics["encode_count"] += len(texts)
                _metrics["total_encode_ms"] += result["latency_ms"]
                if priority == 0:
                    _metrics["batches_high"] += 1
                else:
                    _metrics["batches_low"] += 1
        except Exception as exc:
            result["error"] = str(exc)
            with _metrics_lock:
                _metrics["errors"] += 1
            log.error("Encode worker error: %s", exc)
        finally:
            result["done"].set()


# Start a pool of workers (single worker is fine for CPU-bound FlagModel)
_NUM_WORKERS = int(os.environ.get("RAG_EMBEDDING_WORKERS", "1"))
for i in range(_NUM_WORKERS):
    t = threading.Thread(target=_encode_worker, daemon=True, name=f"bge-worker-{i}")
    t.start()
    log.info("Embedding worker %d started", i)


async def _do_encode(texts: list[str], priority: str = "high") -> tuple[list[list[float]], float]:
    """Submit to priority queue and wait for result."""
    prio = 0 if priority == "high" else 1
    result: dict[str, Any] = {"done": threading.Event()}
    _encode_queue.put((prio, texts, result))

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, result["done"].wait)

    if "error" in result:
        raise RuntimeError(result["error"])
    return result["vectors"], result.get("latency_ms", 0.0)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

import asyncio

app = FastAPI(title="Global RAG Embedding Service")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    priority: str = Field(default="high")


@app.post("/embed")
async def embed(req: EmbedRequest):
    t0 = time.monotonic()

    # Server-side cache for single-text requests
    if len(req.texts) == 1:
        cached = _cache_get(req.texts[0])
        if cached is not None:
            with _metrics_lock:
                _metrics["cache_hits"] += 1
            return {
                "vectors": [cached],
                "dim": len(cached),
                "count": 1,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "cached": True,
            }
        with _metrics_lock:
            _metrics["cache_misses"] += 1

    vectors, encode_ms = await _do_encode(req.texts, req.priority)

    # Cache single results
    if len(req.texts) == 1:
        _cache_put(req.texts[0], vectors[0])

    return {
        "vectors": vectors,
        "dim": len(vectors[0]) if vectors else 0,
        "count": len(vectors),
        "latency_ms": round((time.monotonic() - t0) * 1000, 2),
        "cached": False,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "model": "loaded" if _model is not None else "loading"}


@app.get("/metrics")
async def metrics():
    with _metrics_lock:
        total = _metrics["cache_hits"] + _metrics["cache_misses"]
        hit_rate = _metrics["cache_hits"] / total if total > 0 else 0
        avg_ms = _metrics["total_encode_ms"] / _metrics["encode_count"] if _metrics["encode_count"] > 0 else 0
        snapshot = {
            "encode_count": _metrics["encode_count"],
            "cache_hit_rate": round(hit_rate, 4),
            "cache_hits": _metrics["cache_hits"],
            "cache_misses": _metrics["cache_misses"],
            "avg_encode_ms": round(avg_ms, 2),
            "total_encode_ms": round(_metrics["total_encode_ms"], 2),
            "batches_high": _metrics["batches_high"],
            "batches_low": _metrics["batches_low"],
            "errors": _metrics["errors"],
            "queue_high_depth": _encode_queue.qsize(),
            "cache_size": len(_cache),
        }
    return snapshot


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
