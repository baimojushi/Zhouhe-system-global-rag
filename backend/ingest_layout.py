#!/usr/bin/env python3
"""Windows E:\\RAG layout and safe source-file discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator


DEFAULT_WINDOWS_ROOT = r"E:\RAG"
DEFAULT_WSL_ROOT = "/mnt/e/RAG"

LIBRARY_FOLDERS: tuple[dict[str, str], ...] = (
    {"library_id": "ai-work", "folder_name": "AI工作记录", "node_id": "ai-unclassified"},
    {"library_id": "academic", "folder_name": "学术资料", "node_id": "ac-unclassified"},
    {"library_id": "production", "folder_name": "生产文档", "node_id": "pr-unclassified"},
    {"library_id": "notes", "folder_name": "个人思维笔记", "node_id": "nt-unclassified"},
)

SUPPORTED_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".sh", ".ps1", ".bat", ".cmd",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".csv", ".tsv", ".sql", ".html", ".htm", ".xml", ".css", ".scss",
    ".pdf",
})


def ingest_root() -> Path:
    """Return the configured WSL view of the Windows source directory."""
    raw = os.environ.get("RAG_INGEST_ROOTS", DEFAULT_WSL_ROOT).split(os.pathsep)[0]
    return Path(raw.strip() or DEFAULT_WSL_ROOT).expanduser()


def library_folder(library_id: str, root: Path | None = None) -> Path:
    mapping = next((item for item in LIBRARY_FOLDERS if item["library_id"] == library_id), None)
    if mapping is None:
        raise ValueError(f"library '{library_id}' has no physical source folder")
    return (root or ingest_root()) / mapping["folder_name"]


def layout_status(root: Path | None = None) -> dict[str, Any]:
    base = root or ingest_root()
    return {
        "windows_root": DEFAULT_WINDOWS_ROOT,
        "wsl_root": str(base),
        "exists": base.is_dir(),
        "libraries": [
            {
                **item,
                "windows_path": DEFAULT_WINDOWS_ROOT + "\\" + item["folder_name"],
                "wsl_path": str(base / item["folder_name"]),
                "exists": (base / item["folder_name"]).is_dir(),
            }
            for item in LIBRARY_FOLDERS
        ],
    }


def ensure_layout(root: Path | None = None) -> dict[str, Any]:
    """Create the four document-library folders; association stays virtual."""
    base = root or ingest_root()
    base.mkdir(parents=True, exist_ok=True)
    for item in LIBRARY_FOLDERS:
        (base / item["folder_name"]).mkdir(parents=True, exist_ok=True)
    return layout_status(base)


def iter_library_files(
    library_id: str,
    root: Path | None = None,
    max_files: int = 1000,
    max_file_bytes: int = 100 * 1024 * 1024,
) -> Iterator[Path]:
    """Yield supported regular files without following links outside a library."""
    folder = library_folder(library_id, root).resolve(strict=True)
    emitted = 0
    for candidate in sorted(folder.rglob("*"), key=lambda item: str(item).casefold()):
        if emitted >= max(1, max_files):
            break
        relative = candidate.relative_to(folder)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(folder)
        except ValueError:
            continue
        if resolved.suffix.casefold() not in SUPPORTED_SUFFIXES:
            continue
        if resolved.stat().st_size > max_file_bytes:
            continue
        emitted += 1
        yield resolved

