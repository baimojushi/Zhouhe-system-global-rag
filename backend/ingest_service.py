#!/usr/bin/env python3
"""Reusable E:\\RAG scanning and idempotent ingest-queue orchestration."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from ingest_layout import LIBRARY_FOLDERS, ensure_layout, iter_library_files
except ImportError:
    from backend.ingest_layout import LIBRARY_FOLDERS, ensure_layout, iter_library_files


WaitFunction = Callable[[float], bool]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def queue_ingest_file(
    store: Any,
    path: Path,
    library_id: str,
    target_node_id: str,
    actor: str,
) -> tuple[dict[str, Any], str]:
    """Register one source path and create/reuse its idempotent ingest job."""
    if not path.is_file():
        raise ValueError("指定路径不是文件；文件夹请使用扫描功能")
    stat = path.stat()
    identity = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
    idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    document = store.find_document_by_source_path(library_id, str(path))
    document_state = "existing"
    if document is None:
        document = store.create_document(
            library_id=library_id,
            title=path.name,
            node_id=target_node_id,
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            source_path=str(path),
            source_name=path.name,
            content_hash=hash_file(path),
            size_bytes=stat.st_size,
            index_status="queued",
            actor=actor,
            idempotent=True,
        )
        document_state = "created"
    job = store.queue_ingest(
        library_id,
        target_node_id,
        str(path),
        idempotency_key,
        document_id=document["id"],
    )
    return job, document_state


def scan_ingest_folders(
    store: Any,
    library_id: Optional[str] = None,
    max_files: int = 1000,
    actor: str = "folder-scanner",
    stability_seconds: float = 0,
    wait_fn: Optional[WaitFunction] = None,
) -> dict[str, Any]:
    """Discover, optionally stability-check, and enqueue physical files.

    ``wait_fn`` returns True when shutdown was requested, allowing a 30-second
    stability window to remain interruptible inside the persistent worker.
    """
    layout = ensure_layout()
    mappings = [
        item for item in LIBRARY_FOLDERS
        if library_id is None or item["library_id"] == library_id
    ]
    if not mappings:
        raise ValueError("该知识库不保存原始文件，不能扫描物理目录")

    limit = max(1, int(max_files))
    max_bytes = int(os.environ.get("RAG_MAX_INGEST_FILE_BYTES", str(100 * 1024 * 1024)))
    discovered: list[tuple[dict[str, str], Path]] = []
    errors: list[dict[str, str]] = []
    for mapping in mappings:
        remaining = limit - len(discovered)
        if remaining <= 0:
            break
        try:
            discovered.extend(
                (mapping, path)
                for path in iter_library_files(
                    mapping["library_id"], max_files=remaining, max_file_bytes=max_bytes
                )
            )
        except (OSError, ValueError) as exc:
            errors.append({"path": mapping["folder_name"], "message": str(exc)})

    stable = discovered
    unstable: list[str] = []
    cancelled = False
    if stability_seconds > 0 and discovered:
        initial: dict[str, tuple[int, int]] = {}
        for _, path in discovered:
            try:
                initial[str(path)] = file_signature(path)
            except OSError as exc:
                errors.append({"path": str(path), "message": str(exc)})
        if wait_fn is None:
            def wait_fn(seconds: float) -> bool:
                time.sleep(seconds)
                return False
        cancelled = bool(wait_fn(stability_seconds))
        if cancelled:
            stable = []
        else:
            stable = []
            for mapping, path in discovered:
                try:
                    if initial.get(str(path)) == file_signature(path):
                        stable.append((mapping, path))
                    else:
                        unstable.append(str(path))
                except OSError:
                    unstable.append(str(path))

    submitted: list[dict[str, Any]] = []
    if not cancelled:
        for mapping, path in stable:
            try:
                job, document_state = queue_ingest_file(
                    store, path, mapping["library_id"], mapping["node_id"], actor
                )
                submitted.append({
                    "job_id": job["id"],
                    "state": job["state"],
                    "library_id": mapping["library_id"],
                    "source_path": str(path),
                    "document_id": job["document_id"],
                    "document_state": document_state,
                })
            except Exception as exc:
                errors.append({"path": str(path), "message": str(exc)})

    return {
        "status": "cancelled" if cancelled else "queued",
        "windows_root": layout["windows_root"],
        "wsl_root": layout["wsl_root"],
        "discovered_count": len(discovered),
        "stable_count": len(stable),
        "unstable_count": len(unstable),
        "submitted_count": len(submitted),
        "error_count": len(errors),
        "jobs": submitted[:100],
        "unstable_files": unstable[:100],
        "errors": errors[:100],
        "truncated": len(discovered) >= limit,
    }

