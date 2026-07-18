#!/usr/bin/env python3
"""Persistent Ingest Worker for Knowledge Workbench V2.

Consumes queued ingest_jobs, parses source files into chunks, embeds them
with BGE-M3, and writes to per-library Weaviate collections.

Features:
  - Task lease with heartbeat (auto-reclaim on expiry)
  - Configurable retry with max_retries per job
  - Per-library Weaviate collection writes
  - Graceful shutdown on SIGTERM/SIGINT

Usage:
  python3 ingest_worker.py [--poll-interval 5] [--lease-seconds 300] [--once]
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/opt/global-rag/cache/huggingface")

import weaviate
from weaviate.auth import AuthApiKey
from FlagEmbedding import FlagModel

from knowledge_store import KnowledgeStore, DEFAULT_LIBRARIES

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FILE = Path("/opt/global-rag/logs/ingest_worker.log")
os.makedirs(LOG_FILE.parent, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ingest_worker")

CONTROL_DB_PATH = os.environ.get(
    "RAG_CONTROL_DB", "/opt/global-rag/data/knowledge-control.db"
)
INGEST_ROOTS = [
    Path(p) for p in
    os.environ.get("RAG_INGEST_ROOTS", "/opt/global-rag/kb").split(":")
    if p.strip()
]

WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "localhost")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8080"))
WEAVIATE_GRPC = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))

_worker_id = f"worker-{uuid.uuid4().hex[:8]}"
_shutdown = threading.Event()


# ---------------------------------------------------------------------------
# Weaviate + Model singletons
# ---------------------------------------------------------------------------

_weaviate_client: Optional[weaviate.WeaviateClient] = None
_model: Optional[FlagModel] = None
_collection_cache: dict[str, Any] = {}


def get_weaviate_client() -> weaviate.WeaviateClient:
    global _weaviate_client
    if _weaviate_client is None:
        api_key = os.environ.get("WEAVIATE_API_KEY", "").strip()
        if not api_key:
            env_path = Path("/opt/global-rag/stack/.env")
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("WEAVIATE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"')
                        break
        if not api_key:
            raise RuntimeError("WEAVIATE_API_KEY not configured")
        _weaviate_client = weaviate.connect_to_local(
            host=WEAVIATE_HOST, port=WEAVIATE_PORT, grpc_port=WEAVIATE_GRPC,
            auth_credentials=AuthApiKey(api_key),
        )
        log.info("Weaviate client connected (%s:%d)", WEAVIATE_HOST, WEAVIATE_PORT)
    return _weaviate_client


def get_model() -> FlagModel:
    global _model
    if _model is None:
        log.info("Loading BGE-M3 model...")
        _model = FlagModel("BAAI/bge-m3", cpu="CPU", use_fp16=False)
        log.info("BGE-M3 loaded")
    return _model


def get_library_collection(library_id: str, collection_name: str):
    """Get or create a per-library Weaviate collection.

    Weaviate capitalises the first letter of class names internally,
    so ``kb_production_v1`` becomes ``Kb_production_v1`` in the schema.
    """
    weaviate_name = collection_name[0].upper() + collection_name[1:]
    if weaviate_name in _collection_cache:
        return _collection_cache[weaviate_name]
    client = get_weaviate_client()
    if client.collections.exists(weaviate_name):
        coll = client.collections.get(weaviate_name)
    else:
        log.info("Creating collection '%s' for library '%s'", weaviate_name, library_id)
        coll = client.collections.create(
            name=weaviate_name,
            properties=[
                weaviate.classes.config.Property(name="chunk_id", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="content", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="title", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="heading", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="source_path", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="source_name", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="source_hash", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="mime_type", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="page", data_type=weaviate.classes.config.DataType.INT),
                weaviate.classes.config.Property(name="chunk_index", data_type=weaviate.classes.config.DataType.INT),
                weaviate.classes.config.Property(name="scope", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="modified_at", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="document_id", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="library_id", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="version_id", data_type=weaviate.classes.config.DataType.TEXT),
                weaviate.classes.config.Property(name="node_id", data_type=weaviate.classes.config.DataType.TEXT),
            ],
            vector_config=weaviate.classes.config.Configure.Vectorizer.none(),
        )
    _collection_cache[weaviate_name] = coll
    return coll


# ---------------------------------------------------------------------------
# File parsing & chunking
# ---------------------------------------------------------------------------

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def read_source_file(path: str) -> str:
    """Read file content with encoding detection."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"source file not found: {path}")
    if not p.is_file():
        raise ValueError(f"source path is not a file: {path}")

    allowed = False
    for root in INGEST_ROOTS:
        try:
            p.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ValueError(f"source path outside RAG_INGEST_ROOTS: {path}")

    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return p.read_text(encoding=encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError(f"cannot decode file with supported encodings: {path}")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Core ingest logic
# ---------------------------------------------------------------------------

def process_job(job: dict[str, Any], store: KnowledgeStore) -> tuple[int, str]:
    """Process a single ingest job. Returns (chunks_indexed, weaviate_collection)."""
    source_path = job["source_path"]
    library_id = job["library_id"]
    target_node_id = job["target_node_id"]
    document_id = job.get("document_id") or ""
    version_id = job.get("version_id") or ""

    log.info(
        "Processing job %s: library=%s node=%s path=%s version=%s",
        job["id"], library_id, target_node_id, source_path, version_id,
    )

    library = next(
        (lib for lib in DEFAULT_LIBRARIES if lib["id"] == library_id), None
    )
    if library is None:
        lib_row = store._connect().execute(
            "SELECT * FROM libraries WHERE id = ?", (library_id,)
        ).fetchone()
        if lib_row is None:
            raise ValueError(f"library '{library_id}' not found")
        collection_name = lib_row["collection_name"]
    else:
        collection_name = library["collection_name"]

    collection = get_library_collection(library_id, collection_name)

    content = read_source_file(source_path)
    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_name = Path(source_path).name
    mime_type = "text/plain"
    if source_name.endswith(".py"):
        mime_type = "text/x-python"
    elif source_name.endswith(".md"):
        mime_type = "text/markdown"

    # Update version with content hash and size
    if version_id:
        try:
            conn = store._connect()
            conn.execute(
                """UPDATE document_versions SET content_hash = ?, size_bytes = ?
                   WHERE id = ?""",
                (file_hash[:16], len(content.encode("utf-8")), version_id),
            )
            conn.close()
        except Exception as e:
            log.warning("Failed to update version metadata: %s", e)

    chunks = chunk_text(content)
    if not chunks:
        log.warning("Job %s: no chunks produced from %s", job["id"], source_path)
        return 0, collection_name

    model = get_model()
    texts_to_embed = [f"{source_name} {chunk}" for chunk in chunks]
    vectors = model.encode(texts_to_embed).tolist()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        chunk_id = f"{document_id or 'doc'}-{file_hash[:8]}-{idx}"
        batch.append(weaviate.classes.data.DataObject(
            properties={
                "chunk_id": chunk_id,
                "content": chunk,
                "title": source_name,
                "heading": "",
                "source_path": source_path,
                "source_name": source_name,
                "source_hash": file_hash[:16],
                "mime_type": mime_type,
                "page": 0,
                "chunk_index": idx,
                "scope": "global",
                "modified_at": now_str,
                "document_id": document_id,
                "version_id": version_id,
                "library_id": library_id,
                "node_id": target_node_id,
            },
            vector=vec,
        ))

    collection.data.insert_many(batch)
    log.info("Job %s: indexed %d chunks into %s", job["id"], len(batch), collection_name)
    return len(batch), collection_name


# ---------------------------------------------------------------------------
# Worker main loop
# ---------------------------------------------------------------------------

def heartbeat_loop(store: KnowledgeStore, job_id: str, lease_seconds: int) -> None:
    """Renew lease periodically until job completes or shutdown."""
    interval = max(lease_seconds // 3, 10)
    while not _shutdown.is_set():
        _shutdown.wait(interval)
        if _shutdown.is_set():
            break
        try:
            ok = store.renew_lease(job_id, _worker_id, lease_seconds)
            if not ok:
                log.warning("Heartbeat failed for job %s (lease lost)", job_id)
                break
        except Exception as exc:
            log.error("Heartbeat error for job %s: %s", job_id, exc)


def run_worker(
    poll_interval: float = 5.0,
    lease_seconds: int = 300,
    run_once: bool = False,
) -> None:
    """Main worker loop."""
    store = KnowledgeStore(CONTROL_DB_PATH)
    log.info(
        "Ingest worker %s started (db=%s, poll=%.1fs, lease=%ds)",
        _worker_id, CONTROL_DB_PATH, poll_interval, lease_seconds,
    )

    while not _shutdown.is_set():
        reclaimed = store.release_expired_leases()
        if reclaimed:
            log.info("Reclaimed %d expired leases", reclaimed)

        job = store.claim_next_job(_worker_id, lease_seconds)
        if job is None:
            if run_once:
                break
            _shutdown.wait(poll_interval)
            continue

        hb_thread = threading.Thread(
            target=heartbeat_loop, args=(store, job["id"], lease_seconds),
            daemon=True,
        )
        hb_thread.start()

        try:
            chunks, collection_name = process_job(job, store)
            version_id = job.get("version_id") or ""

            # Complete the version
            if version_id:
                store.complete_version(version_id, chunks, collection_name)
                # Atomically activate this version
                store.activate_version(version_id)
                log.info("Version %s activated with %d chunks", version_id, chunks)

            # Complete the job
            store.complete_job(job["id"], chunks_indexed=chunks)
            log.info("Job %s completed: %d chunks indexed", job["id"], chunks)
        except Exception as exc:
            log.error("Job %s failed: %s", job["id"], exc, exc_info=True)
            version_id = job.get("version_id") or ""
            if version_id:
                try:
                    store.fail_version(version_id, str(exc))
                except Exception as ver_exc:
                    log.error("Failed to mark version as failed: %s", ver_exc)
            try:
                store.fail_job(job["id"], str(exc))
            except Exception as fail_exc:
                log.error("Failed to record job failure: %s", fail_exc)

        if run_once:
            break

    log.info("Ingest worker %s shutting down", _worker_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _handle_signal(signum: int, _frame: Any) -> None:
    log.info("Received signal %d, requesting shutdown...", signum)
    _shutdown.set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge Workbench V2 Ingest Worker")
    parser.add_argument("--poll-interval", type=float, default=5.0,
                        help="Seconds between poll attempts (default: 5)")
    parser.add_argument("--lease-seconds", type=int, default=300,
                        help="Job lease duration in seconds (default: 300)")
    parser.add_argument("--once", action="store_true",
                        help="Process one job and exit (for testing)")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    run_worker(
        poll_interval=args.poll_interval,
        lease_seconds=args.lease_seconds,
        run_once=args.once,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
