#!/usr/bin/env python3
"""Persistent Ingest Worker for Knowledge Workbench V2.

Consumes queued ingest_jobs, parses source files into chunks, embeds them
with BGE-M3, and writes to per-library Weaviate collections.

PDF files are routed to the MinerU document parsing service for structured
extraction (markdown, layout, tables).  Text files use the built-in parser.

Features:
  - Task lease with heartbeat (auto-reclaim on expiry)
  - Configurable retry with max_retries per job
  - Per-library Weaviate collection writes
  - MinerU integration with async task recovery
  - Graceful shutdown on SIGTERM/SIGINT

Usage:
  python3 ingest_worker.py [--poll-interval 5] [--lease-seconds 300] [--once]
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
from embedding_client import encode

from knowledge_store import KnowledgeStore, StoreConflict
from ingest_service import scan_ingest_folders
from document_parser import (
    get_parser,
    submit_and_persist,
    poll_and_materialize,
    ARTIFACT_ROOT,
)
from mineru_client import MinerUConnectionError, MinerUTimeoutError
from post_parse_filename import rename_after_mineru, recover_pending_file_renames

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
    os.environ.get("RAG_INGEST_ROOTS", "/mnt/e/RAG").split(os.pathsep)
    if p.strip()
]

WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "localhost")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8080"))
WEAVIATE_GRPC = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))

_worker_id = f"worker-{uuid.uuid4().hex[:8]}"
_shutdown = threading.Event()


# ---------------------------------------------------------------------------
# Weaviate singleton (embedding delegated to remote service)
# ---------------------------------------------------------------------------

_weaviate_client: Optional[weaviate.WeaviateClient] = None
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
    p = Path(path).expanduser().resolve(strict=True)
    if not p.exists():
        raise FileNotFoundError(f"source file not found: {path}")
    if not p.is_file():
        raise ValueError(f"source path is not a file: {path}")

    allowed = False
    for root in INGEST_ROOTS:
        try:
            resolved_root = root.expanduser().resolve(strict=True)
            p.relative_to(resolved_root)
            allowed = True
            break
        except (FileNotFoundError, ValueError):
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
# PDF detection
# ---------------------------------------------------------------------------

PDF_SUFFIXES = frozenset({".pdf"})


def is_pdf_file(source_path: str) -> bool:
    return Path(source_path).suffix.casefold() in PDF_SUFFIXES


# ---------------------------------------------------------------------------
# MinerU PDF processing
# ---------------------------------------------------------------------------

def _chunk_markdown(
    md_content: str,
    source_name: str,
    chunk_size: int = 700,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """Split MinerU markdown into chunks with heading awareness.

    Returns list of dicts with ``content``, ``heading``, ``chunk_index``.
    """
    if not md_content.strip():
        return []

    lines = md_content.split("\n")
    chunks: list[dict[str, Any]] = []
    current_heading = ""
    buffer: list[str] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer, buffer_len
        text = "\n".join(buffer).strip()
        if text:
            chunks.append({
                "content": text,
                "heading": current_heading,
            })
        buffer = []
        buffer_len = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_level = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= heading_level <= 6:
                flush()
                current_heading = stripped.lstrip("#").strip()
                continue

        buffer.append(line)
        buffer_len += len(line)
        if buffer_len >= chunk_size:
            flush()
            overlap_text = "\n".join(buffer[-3:]) if len(buffer) >= 3 else "\n".join(buffer)
            buffer = [overlap_text] if overlap_text.strip() else []
            buffer_len = len(overlap_text)

    flush()
    return [
        {"content": c["content"], "heading": c["heading"], "chunk_index": i}
        for i, c in enumerate(chunks)
    ]


def _chunk_from_content_list(
    content_list: list[dict[str, Any]],
    source_name: str,
    chunk_size: int = 700,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """Chunk MinerU content_list with page/heading/block-type awareness.

    Each returned chunk dict includes:
      - content:       assembled text
      - heading:       current section heading
      - page:          page number (0-based)
      - block_type:    dominant block type
      - asset_refs:    list of referenced image/chart paths
      - chunk_index:   sequential index

    Skips structural blocks (header, footer, page_number, aside_text).
    """
    if not content_list:
        return []

    # Filter to content-bearing blocks, grouped by page
    SKIP_TYPES = frozenset({"header", "footer", "page_number", "aside_text"})

    chunks: list[dict[str, Any]] = []
    current_heading = ""
    current_page = 0
    buffer: list[str] = []
    buffer_len = 0
    buffer_assets: list[str] = []
    buffer_types: set[str] = set()

    def flush() -> None:
        nonlocal buffer, buffer_len, buffer_assets, buffer_types
        text = "\n".join(buffer).strip()
        if text:
            # Determine dominant block type (prefer non-text)
            dominant = "text"
            for bt in ("table", "chart", "image", "formula"):
                if bt in buffer_types:
                    dominant = bt
                    break
            chunks.append({
                "content": text,
                "heading": current_heading,
                "page": current_page,
                "block_type": dominant,
                "asset_refs": list(buffer_assets),
            })
        buffer = []
        buffer_len = 0
        buffer_assets = []
        buffer_types = set()

    for block in content_list:
        if not isinstance(block, dict):
            continue

        btype = block.get("type", "")
        if btype in SKIP_TYPES:
            continue

        page = block.get("page_idx", 0)

        # Detect page boundary → flush
        if page != current_page and buffer:
            flush()
            current_page = page

        # Detect heading (text with text_level)
        if btype == "text" and "text_level" in block:
            level = block["text_level"]
            if 1 <= level <= 6:
                flush()
                current_heading = block.get("text", "").strip()
                continue

        # Collect asset references
        assets: list[str] = []
        if btype in ("image", "chart"):
            img = block.get("img_path", "")
            if img:
                assets.append(img)
            # Also add caption as content
            caption = block.get("image_caption") or block.get("chart_caption") or []
            if caption:
                caption_text = " ".join(caption) if isinstance(caption, list) else str(caption)
                buffer.append(f"[{btype}] {caption_text}")
                buffer_len += len(buffer[-1])
        elif btype == "table":
            # Table content is in the markdown, but we mark the type
            table_html = block.get("html", block.get("text", ""))
            if table_html:
                buffer.append(f"[table] {table_html}")
                buffer_len += len(buffer[-1])

        # Regular text
        text = block.get("text", block.get("content", "")).strip()
        if text:
            buffer.append(text)
            buffer_len += len(text)

        buffer_types.add(btype)
        buffer_assets.extend(assets)

        # Flush if buffer exceeds chunk_size
        if buffer_len >= chunk_size:
            flush()

    flush()

    return [
        {
            "content": c["content"],
            "heading": c["heading"],
            "page": c["page"],
            "block_type": c["block_type"],
            "asset_refs": c["asset_refs"],
            "chunk_index": i,
        }
        for i, c in enumerate(chunks)
    ]


def process_pdf_job(
    job: dict[str, Any],
    store: KnowledgeStore,
    force_reparse: bool = False,
) -> tuple[int, str]:
    """Process a PDF ingest job via MinerU.

    Creates a parse_job, submits to MinerU, polls until complete,
    fetches the markdown result, chunks it, embeds, and indexes into Weaviate.

    If ``force_reparse`` is False (default), checks for a cached parse result
    with the same source_hash + parser_version + config_fingerprint.

    Returns (chunks_indexed, weaviate_collection).
    """
    source_path = job["source_path"]
    library_id = job["library_id"]
    target_node_id = job["target_node_id"]
    document_id = job.get("document_id") or ""
    version_id = job.get("version_id") or ""
    ingest_job_id = job["id"]

    log.info(
        "PDF job %s: processing (path=%s)", ingest_job_id, source_path
    )

    # Compute source hash
    path = Path(source_path)
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(64 * 1024), b""):
            sha256.update(block)
    source_hash = sha256.hexdigest()
    config_fingerprint = "v1"

    # Cache lookup: same source_hash + parser_version + config_fingerprint
    if not force_reparse:
        cached = _find_cached_parse(store, source_hash, config_fingerprint)
        if cached is not None:
            log.info(
                "PDF job %s: reusing cached parse (artifact_dir=%s)",
                ingest_job_id, cached,
            )
            indexed_job, rename_outcome = rename_after_mineru(store, job, cached)
            log.info(
                "PDF filename stage: job=%s state=%s name=%s",
                ingest_job_id, rename_outcome.state,
                Path(indexed_job["source_path"]).name,
            )
            return _index_from_artifact(
                store, indexed_job, indexed_job["source_path"], source_hash, cached,
            )

    # Create parse_job record — guard against stale leftovers from retry races
    try:
        parse_job = store.create_parse_job(
            ingest_job_id=ingest_job_id,
            document_id=document_id,
            version_id=version_id,
            source_hash=source_hash,
            config_fingerprint=config_fingerprint,
        )
    except Exception as exc:
        log.warning("create_parse_job failed for %s: %s — cleaning stale parse_job and retrying", ingest_job_id, exc)
        # Must use the same connection/transaction that create_parse_job uses
        conn = store._connect()
        conn.execute("DELETE FROM parse_jobs WHERE ingest_job_id = ?", (ingest_job_id,))
        conn.commit()
        parse_job = store.create_parse_job(
            ingest_job_id=ingest_job_id,
            document_id=document_id,
            version_id=version_id,
            source_hash=source_hash,
            config_fingerprint=config_fingerprint,
        )
    log.info("Created parse_job %s for ingest %s", parse_job["id"], ingest_job_id)

    # Submit to MinerU
    try:
        updated = submit_and_persist(store, parse_job, source_path)
        parse_job_id = updated["id"]
        external_task_id = updated.get("external_task_id", "")
        log.info(
            "Submitted to MinerU: parse_job=%s task=%s",
            parse_job_id, external_task_id,
        )
    except (MinerUConnectionError, RuntimeError) as exc:
        store.update_parse_job(
            parse_job["id"], state="failed", error=str(exc)
        )
        raise

    # Poll and materialize
    try:
        final_parse = poll_and_materialize(
            store, updated, source_path, document_id, version_id,
        )
        log.info(
            "MinerU parse complete: parse_job=%s artifact_dir=%s",
            final_parse["id"], final_parse.get("artifact_dir", ""),
        )
    except (MinerUTimeoutError, MinerUConnectionError, RuntimeError) as exc:
        store.update_parse_job(
            parse_job["id"], state="failed", error=str(exc)
        )
        raise

    artifact_dir = final_parse.get("artifact_dir", "")
    indexed_job, rename_outcome = rename_after_mineru(store, job, artifact_dir)
    log.info(
        "PDF filename stage: job=%s state=%s name=%s",
        ingest_job_id, rename_outcome.state,
        Path(indexed_job["source_path"]).name,
    )
    return _index_from_artifact(
        store, indexed_job, indexed_job["source_path"], source_hash, artifact_dir,
    )


def _find_cached_parse(
    store: KnowledgeStore,
    source_hash: str,
    config_fingerprint: str,
) -> Optional[str]:
    """Look for an existing parse result with matching hash + fingerprint.

    Returns the artifact_dir path if a cached result exists, else None.
    """
    jobs = store.list_parse_jobs(state="parsed", limit=100)
    for pj in jobs:
        if (pj.get("source_hash", "") == source_hash
                and pj.get("config_fingerprint", "") == config_fingerprint
                and pj.get("parser_version", "") == "3.4.4"
                and pj.get("artifact_dir", "")):
            ad = pj["artifact_dir"]
            if Path(ad).exists():
                return ad
    return None


def _index_from_artifact(
    store: KnowledgeStore,
    job: dict[str, Any],
    source_path: str,
    source_hash: str,
    artifact_dir: str,
) -> tuple[int, str]:
    """Read parsed artifacts, chunk, embed, and index into Weaviate.

    Shared by both fresh parses and cache hits.
    """
    library_id = job["library_id"]
    target_node_id = job["target_node_id"]
    document_id = job.get("document_id") or ""
    version_id = job.get("version_id") or ""
    ingest_job_id = job["id"]
    path = Path(source_path)
    source_name = path.name

    md_path = Path(artifact_dir) / "document.md"
    cl_path = Path(artifact_dir) / "content_list.json"

    md_content = ""
    content_list: list[dict[str, Any]] = []
    if md_path.exists():
        md_content = md_path.read_text(encoding="utf-8")
    if cl_path.exists():
        try:
            raw = cl_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, list):
                content_list = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("Failed to parse content_list.json: %s", exc)

    # Chunk
    if content_list:
        chunks = _chunk_from_content_list(content_list, source_name)
    else:
        chunks = _chunk_markdown(md_content, source_name)

    if not chunks:
        log.warning("Job %s: no chunks from artifact %s", ingest_job_id, artifact_dir)
        return 0, ""

    # Embed and index
    library = store.get_library(library_id)
    collection_name = library["collection_name"]
    collection = get_library_collection(library_id, collection_name)

    texts_to_embed = [f"{source_name} {c['content']}" for c in chunks]
    vectors = encode(texts_to_embed, priority="low")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        chunk_id = f"{version_id or document_id or source_hash[:16]}-{idx}"
        asset_refs = chunk.get("asset_refs", [])
        batch.append(weaviate.classes.data.DataObject(
            properties={
                "chunk_id": chunk_id,
                "content": chunk["content"],
                "title": source_name,
                "heading": chunk.get("heading", ""),
                "source_path": source_path,
                "source_name": source_name,
                "source_hash": source_hash[:16],
                "mime_type": "application/pdf",
                "page": chunk.get("page", 0),
                "chunk_index": idx,
                "scope": "global",
                "modified_at": now_str,
                "document_id": document_id,
                "version_id": version_id,
                "library_id": library_id,
                "node_id": target_node_id,
                "block_type": chunk.get("block_type", "text"),
                "asset_refs": ",".join(asset_refs) if asset_refs else "",
            },
            vector=vec,
            uuid=str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"global-rag:{chunk_id}"
            )),
        ))

    collection.data.insert_many(batch)
    log.info(
        "Job %s: indexed %d chunks into %s (from %s)",
        ingest_job_id, len(batch), collection_name,
        "cache" if Path(artifact_dir).exists() else "fresh parse",
    )
    return len(batch), collection_name


# ---------------------------------------------------------------------------
# Stale parse job recovery
# ---------------------------------------------------------------------------

def recover_stale_parse_jobs(store: KnowledgeStore) -> int:
    """Recover parse jobs that were in 'parsing' state when the worker stopped.

    Polls MinerU for each stale job's external_task_id.  If the task
    completed while we were away, materialize the result.  If it's still
    running, leave it in 'parsing' for the next poll cycle.

    Returns the number of recovered jobs.
    """
    stale = store.list_parse_jobs(state="parsing", limit=500)
    if not stale:
        return 0

    log.info("Found %d stale parse jobs to recover", len(stale))
    recovered = 0
    for pj in stale:
        task_id = pj.get("external_task_id", "")
        if not task_id:
            log.warning("Stale parse job %s has no external_task_id, marking failed", pj["id"])
            store.update_parse_job(pj["id"], state="failed", error="No external_task_id on recovery")
            continue

        try:
            parser = get_parser("mineru")
            if parser is None:
                log.error("MinerU parser not available for recovery")
                break
            status = parser.status(task_id)
            if status.state == "parsed":
                log.info("Recovering completed parse job %s (task=%s)", pj["id"], task_id)
                poll_and_materialize(
                    store, pj,
                    pj.get("source_hash", ""),
                    pj["document_id"],
                    pj["version_id"],
                )
                recovered += 1
            elif status.state == "failed":
                log.warning("Stale parse job %s failed on MinerU side: %s", pj["id"], status.error)
                store.update_parse_job(pj["id"], state="failed", error=status.error)
            else:
                log.info("Stale parse job %s still running (state=%s), leaving it", pj["id"], status.state)
        except MinerUConnectionError as exc:
            log.warning("Cannot reach MinerU for recovery: %s", exc)
            break
        except Exception as exc:
            log.error("Error recovering parse job %s: %s", pj["id"], exc)

    return recovered


# ---------------------------------------------------------------------------
# Core ingest logic
# ---------------------------------------------------------------------------

def process_job(job: dict[str, Any], store: KnowledgeStore) -> tuple[int, str]:
    """Process a single ingest job. Returns (chunks_indexed, weaviate_collection).

    PDF files are routed to MinerU; text files use the built-in parser.
    """
    source_path = job["source_path"]

    # Route PDF files to MinerU
    if is_pdf_file(source_path):
        return process_pdf_job(job, store)

    # Text file processing (existing logic)
    library_id = job["library_id"]
    target_node_id = job["target_node_id"]
    document_id = job.get("document_id") or ""
    version_id = job.get("version_id") or ""

    log.info(
        "Processing job %s: library=%s node=%s path=%s version=%s",
        job["id"], library_id, target_node_id, source_path, version_id,
    )

    library = store.get_library(library_id)
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

    chunks = chunk_text(content)
    if not chunks:
        log.warning("Job %s: no chunks produced from %s", job["id"], source_path)
        return 0, collection_name

    texts_to_embed = [f"{source_name} {chunk}" for chunk in chunks]
    vectors = encode(texts_to_embed, priority="low")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        chunk_id = f"{version_id or document_id or file_hash[:16]}-{idx}"
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
            uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, f"global-rag:{chunk_id}")),
        ))

    collection.data.insert_many(batch)
    log.info("Job %s: indexed %d chunks into %s", job["id"], len(batch), collection_name)
    return len(batch), collection_name


# ---------------------------------------------------------------------------
# Worker main loop
# ---------------------------------------------------------------------------

def heartbeat_loop(
    store: KnowledgeStore,
    job_id: str,
    lease_seconds: int,
    stop_event: threading.Event,
    lease_lost: threading.Event,
) -> None:
    """Renew lease periodically until job completes or shutdown."""
    interval = max(lease_seconds // 3, 10)
    while not _shutdown.is_set() and not stop_event.is_set():
        stop_event.wait(interval)
        if _shutdown.is_set() or stop_event.is_set():
            break
        try:
            ok = store.renew_lease(job_id, _worker_id, lease_seconds)
            if not ok:
                log.warning("Heartbeat failed for job %s (lease lost)", job_id)
                lease_lost.set()
                break
        except Exception as exc:
            log.error("Heartbeat error for job %s: %s", job_id, exc)
            lease_lost.set()
            break


def auto_scan_loop(
    store: KnowledgeStore,
    interval_seconds: int,
    stability_seconds: int,
) -> None:
    """Periodically discover stable files under E:\\RAG and queue them."""
    log.info(
        "Automatic E:\\RAG scan enabled (interval=%ds, stability=%ds)",
        interval_seconds,
        stability_seconds,
    )
    while not _shutdown.is_set():
        try:
            result = scan_ingest_folders(
                store,
                max_files=int(os.environ.get("RAG_AUTO_SCAN_MAX_FILES", "5000")),
                actor="automatic-folder-scanner",
                stability_seconds=stability_seconds,
                wait_fn=_shutdown.wait,
            )
            if result["status"] == "cancelled":
                break
            log.info(
                "Automatic scan: discovered=%d stable=%d submitted=%d deferred=%d errors=%d",
                result["discovered_count"],
                result["stable_count"],
                result["submitted_count"],
                result["unstable_count"],
                result["error_count"],
            )
        except Exception as exc:
            log.error("Automatic E:\\RAG scan failed: %s", exc, exc_info=True)
        if _shutdown.wait(max(30, interval_seconds)):
            break


def run_worker(
    poll_interval: float = 5.0,
    lease_seconds: int = 300,
    run_once: bool = False,
    auto_scan_seconds: int = 300,
    stability_seconds: int = 30,
) -> None:
    """Main worker loop."""
    store = KnowledgeStore(CONTROL_DB_PATH)
    log.info(
        "Ingest worker %s started (db=%s, poll=%.1fs, lease=%ds)",
        _worker_id, CONTROL_DB_PATH, poll_interval, lease_seconds,
    )

    # Reconcile the narrow crash window after the same-directory disk rename
    # but before the SQLite path transaction committed.
    try:
        recovered_names = recover_pending_file_renames(store)
        if recovered_names:
            log.info("Recovered %d pending PDF filename transactions", recovered_names)
    except Exception as exc:
        log.warning("PDF filename recovery failed (non-fatal): %s", exc)

    # Recover stale parse jobs from previous run
    try:
        recovered = recover_stale_parse_jobs(store)
        if recovered:
            log.info("Recovered %d stale parse jobs", recovered)
    except Exception as exc:
        log.warning("Parse job recovery failed (non-fatal): %s", exc)

    scan_thread: Optional[threading.Thread] = None
    if auto_scan_seconds > 0 and not run_once:
        scan_thread = threading.Thread(
            target=auto_scan_loop,
            args=(store, auto_scan_seconds, max(0, stability_seconds)),
            name="rag-folder-scanner",
            daemon=True,
        )
        scan_thread.start()

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

        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        hb_thread = threading.Thread(
            target=heartbeat_loop,
            args=(store, job["id"], lease_seconds, heartbeat_stop, lease_lost),
            daemon=True,
        )
        hb_thread.start()

        try:
            chunks, collection_name = process_job(job, store)
            if lease_lost.is_set():
                raise StoreConflict(
                    f"job '{job['id']}' lost its lease before activation"
                )
            store.finalize_ingest_job(
                job["id"], _worker_id, chunks, collection_name
            )
            log.info("Job %s completed: %d chunks indexed", job["id"], chunks)
        except Exception as exc:
            log.error("Job %s failed: %s", job["id"], exc, exc_info=True)
            if not lease_lost.is_set():
                try:
                    store.fail_job(job["id"], _worker_id, str(exc))
                except Exception as fail_exc:
                    log.error("Failed to record job failure: %s", fail_exc)
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=1)

        if run_once:
            break

    if scan_thread is not None:
        scan_thread.join(timeout=2)
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
    parser.add_argument(
        "--auto-scan-seconds",
        type=int,
        default=int(os.environ.get("RAG_AUTO_SCAN_SECONDS", "300")),
        help="Seconds between E:\\RAG scans; 0 disables automatic scanning",
    )
    parser.add_argument(
        "--stability-seconds",
        type=int,
        default=int(os.environ.get("RAG_FILE_STABILITY_SECONDS", "30")),
        help="File size/mtime stability window before queueing",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    run_worker(
        poll_interval=args.poll_interval,
        lease_seconds=args.lease_seconds,
        run_once=args.once,
        auto_scan_seconds=args.auto_scan_seconds,
        stability_seconds=args.stability_seconds,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
