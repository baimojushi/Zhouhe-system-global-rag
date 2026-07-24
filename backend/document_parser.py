#!/usr/bin/env python3
"""Document parser abstraction layer.

Defines a common interface for document parsing backends.  The initial
implementation wraps the MinerU HTTP API; future backends (Word, web,
OCR) can implement the same interface without changing the core worker.

Environment variables:
  RAG_MINERU_ENABLED       — set "true" to enable MinerU parsing (default: true)
  RAG_MINERU_API_URL       — MinerU API base URL
  RAG_MINERU_ARTIFACT_ROOT — permanent artifact storage directory
  RAG_PDF_MAX_BYTES        — maximum PDF file size in bytes (default: 500MB)
  RAG_PDF_ALLOW_PARTIAL    — allow partial parse results (default: false)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from knowledge_store import KnowledgeStore

log = logging.getLogger("document_parser")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINERU_ENABLED = os.environ.get("RAG_MINERU_ENABLED", "true").lower() in ("1", "true", "yes")
MINERU_API_URL = os.environ.get("RAG_MINERU_API_URL", "http://127.0.0.1:18000")
ARTIFACT_ROOT = Path(
    os.environ.get("RAG_MINERU_ARTIFACT_ROOT", "/opt/global-rag/derived/mineru")
)
PDF_MAX_BYTES = int(os.environ.get("RAG_PDF_MAX_BYTES", str(500 * 1024 * 1024)))
PDF_ALLOW_PARTIAL = os.environ.get("RAG_PDF_ALLOW_PARTIAL", "false").lower() in ("1", "true", "yes")
MINERU_BACKEND = os.environ.get("RAG_MINERU_BACKEND", "hybrid-engine")
MINERU_EFFORT = os.environ.get("RAG_MINERU_EFFORT", "medium")
MINERU_LARGE_FILE_BYTES = int(
    os.environ.get("RAG_MINERU_LARGE_FILE_BYTES", str(50 * 1024 * 1024))
)
MINERU_LARGE_FILE_EFFORT = os.environ.get("RAG_MINERU_LARGE_FILE_EFFORT", "medium")
MINERU_PARSE_METHOD = os.environ.get("RAG_MINERU_PARSE_METHOD", "auto")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ParseStatus:
    """Unified parse status returned by all parser backends."""
    state: str  # queued / submitting / parsing / materializing / parsed / degraded / failed
    progress: int = 0
    external_task_id: str = ""
    error: str = ""
    artifact_dir: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """Structured parse result."""
    document_id: str
    version_id: str
    md_content: str
    content_list: list[Any]
    pages: int
    manifest: dict[str, Any]
    artifact_dir: str


# ---------------------------------------------------------------------------
# Abstract parser
# ---------------------------------------------------------------------------

class DocumentParser(ABC):
    """Abstract document parser interface.

    Subclasses implement the actual parsing backend.  The core worker
    calls these methods without knowing which backend is active.
    """

    @abstractmethod
    def submit(self, source_path: str, request_id: str) -> str:
        """Submit a document for parsing.

        Args:
            source_path: Absolute path to the source file.
            request_id: Unique idempotency key for this submission.

        Returns:
            An external task ID that can be used for status polling.
        """
        ...

    @abstractmethod
    def status(self, task_id: str) -> ParseStatus:
        """Query the current status of a parse task."""
        ...

    @abstractmethod
    def fetch(self, task_id: str, destination: str) -> ParsedDocument:
        """Fetch completed parse results and materialize them to ``destination``.

        Returns a ParsedDocument with the structured content.
        """
        ...

    @abstractmethod
    def cancel(self, task_id: str) -> None:
        """Cancel a running parse task if supported."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Return the parser name (e.g. 'mineru')."""
        ...

    @abstractmethod
    def version(self) -> str:
        """Return the parser version string."""
        ...


# ---------------------------------------------------------------------------
# MinerU parser implementation
# ---------------------------------------------------------------------------

class MinerUParser(DocumentParser):
    """Document parser backed by the MinerU HTTP API."""

    def __init__(
        self,
        api_url: str = MINERU_API_URL,
        artifact_root: Path = ARTIFACT_ROOT,
        max_file_bytes: int = PDF_MAX_BYTES,
        allow_partial: bool = PDF_ALLOW_PARTIAL,
    ):
        from mineru_client import MinerUClient
        self.client = MinerUClient(base_url=api_url)
        self.artifact_root = artifact_root
        self.max_file_bytes = max_file_bytes
        self.allow_partial = allow_partial

    def name(self) -> str:
        return "mineru"

    def version(self) -> str:
        return "3.4.4"

    def _check_file(self, source_path: str) -> Path:
        path = Path(source_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise ValueError(
                f"File too large: {size} bytes exceeds {self.max_file_bytes}"
            )
        return path

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _config_fingerprint(self) -> str:
        """Return a hash of the current MinerU configuration for cache invalidation."""
        raw = json.dumps({
            "api_url": self.client.base_url,
            "allow_partial": self.allow_partial,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def submit(self, source_path: str, request_id: str) -> str:
        """Submit a PDF to MinerU for async parsing.

        Returns the MinerU task ID (external_task_id).
        Requests both markdown and structured content_list.
        """
        path = self._check_file(source_path)
        log.info("Submitting %s to MinerU (request_id=%s)", path.name, request_id)
        task = self.client.submit_task(
            str(path),
            return_md=True,
            return_content_list=True,
        )
        log.info(
            "MinerU task %s submitted for %s (queued_ahead=%d)",
            task.task_id, path.name, task.queued_ahead,
        )
        return task.task_id

    def status(self, task_id: str) -> ParseStatus:
        """Query MinerU task status and map to unified ParseStatus."""
        raw = self.client.get_task_status(task_id)

        # Map MinerU states to unified states
        state_map = {
            "pending": "parsing",
            "processing": "parsing",
            "completed": "parsed",
            "failed": "failed",
        }
        state = state_map.get(raw.status, "parsing")

        progress = 0
        if raw.status == "completed":
            progress = 100
        elif raw.status == "processing":
            progress = 50

        return ParseStatus(
            state=state,
            progress=progress,
            external_task_id=task_id,
            error=raw.error,
        )

    def fetch(self, task_id: str, destination: str) -> ParsedDocument:
        """Fetch MinerU result and materialize artifacts to ``destination``."""
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)

        # Fetch the result from MinerU
        result = self.client.get_task_result(task_id)

        # Write markdown
        md_path = dest / "document.md"
        md_path.write_text(result.md_content, encoding="utf-8")

        # Write content list if present
        if result.content_list:
            cl_path = dest / "content_list.json"
            cl_path.write_text(
                json.dumps(result.content_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # Build manifest
        manifest = {
            "parser_name": self.name(),
            "parser_version": self.version(),
            "mineru_task_id": task_id,
            "mineru_backend": result.backend,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "artifacts": {
                "document.md": str(md_path),
            },
        }
        if result.content_list:
            manifest["artifacts"]["content_list.json"] = str(cl_path)

        manifest_path = dest / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Count pages from content_list
        pages = len(result.content_list) if result.content_list else 0
        if not pages and result.md_content:
            pages = 1  # At least one page if there's content

        return ParsedDocument(
            document_id="",
            version_id="",
            md_content=result.md_content,
            content_list=result.content_list,
            pages=pages,
            manifest=manifest,
            artifact_dir=str(dest),
        )

    def cancel(self, task_id: str) -> None:
        """MinerU does not support task cancellation via API."""
        log.warning("MinerU task %s cannot be cancelled via API", task_id)


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------

_parsers: dict[str, type[DocumentParser]] = {}


def register_parser(name: str, parser_cls: type[DocumentParser]) -> None:
    _parsers[name] = parser_cls


def get_parser(name: str = "mineru") -> Optional[DocumentParser]:
    """Get a parser instance by name. Returns None if not available."""
    cls = _parsers.get(name)
    if cls is None:
        return None
    return cls()


def available_parsers() -> list[str]:
    return list(_parsers.keys())


# Register built-in parsers
register_parser("mineru", MinerUParser)


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

def submit_and_persist(
    store: KnowledgeStore,
    parse_job: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    """Submit a parse job to the active parser and persist the external task ID.

    Returns the updated parse_job record.
    """
    parser_name = parse_job.get("parser_name", "mineru")
    parser = get_parser(parser_name)
    if parser is None:
        raise RuntimeError(f"Parser '{parser_name}' not registered")

    external_id = parser.submit(source_path, parse_job["id"])
    return store.update_parse_job(
        parse_job["id"],
        state="parsing",
        external_task_id=external_id,
        submit_attempts=1,
    )


def poll_and_materialize(
    store: KnowledgeStore,
    parse_job: dict[str, Any],
    source_path: str,
    document_id: str,
    version_id: str,
) -> dict[str, Any]:
    """Poll a running parse job until complete, then materialize artifacts.

    Returns the final parse_job record.
    """
    parser_name = parse_job.get("parser_name", "mineru")
    parser = get_parser(parser_name)
    if parser is None:
        raise RuntimeError(f"Parser '{parser_name}' not registered")

    task_id = parse_job.get("external_task_id", "")
    if not task_id:
        raise ValueError("Parse job has no external_task_id")

    # Poll until complete
    status = parser.status(task_id)
    if status.state == "parsing":
        from mineru_client import MinerUTimeoutError
        try:
            parser.client.poll_until_complete(task_id)
        except MinerUTimeoutError as exc:
            store.update_parse_job(
                parse_job["id"],
                state="failed",
                error=str(exc),
                poll_failures=1,
            )
            raise

    # Check final status
    final_status = parser.status(task_id)
    if final_status.state == "failed":
        store.update_parse_job(
            parse_job["id"],
            state="failed",
            error=final_status.error or "MinerU task failed",
            poll_failures=1,
        )
        raise RuntimeError(
            f"Parse job {parse_job['id']} failed: {final_status.error}"
        )

    # Materialize artifacts
    artifact_dir = str(
        ARTIFACT_ROOT / document_id / version_id
    )
    tmp_dir = artifact_dir + ".tmp"
    try:
        parsed = parser.fetch(task_id, tmp_dir)

        # Atomic rename
        final_dir = Path(artifact_dir)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(tmp_dir, str(final_dir))

        # Update manifest with document metadata
        manifest = dict(parsed.manifest)
        manifest["document_id"] = document_id
        manifest["version_id"] = version_id
        manifest["source_hash"] = parse_job.get("source_hash", "")
        manifest["pages"] = parsed.pages
        manifest["config_fingerprint"] = parse_job.get("config_fingerprint", "")
        manifest_path = final_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return store.update_parse_job(
            parse_job["id"],
            state="parsed",
            progress=100,
            artifact_dir=str(final_dir),
            manifest_json=json.dumps(manifest, ensure_ascii=False),
        )
    except Exception as exc:
        # Clean up temp directory on failure
        tmp = Path(tmp_dir)
        if tmp.exists():
            shutil.rmtree(tmp_dir)
        store.update_parse_job(
            parse_job["id"],
            state="failed",
            error=str(exc),
        )
        raise
