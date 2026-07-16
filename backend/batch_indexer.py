#!/usr/bin/env python3
"""
RAG Batch Indexer — Phase 2
============================
Batch index files into Weaviate KnowledgeChunk collection with:
  - Docling parser (PDF/Office/Markdown)
  - SHA-256 incremental indexing (skip unchanged files)
  - Content-aware chunking with token limits
  - Self-provided 1024-dim vectors via BGE-M3
  - Per-file stats and error logging

Usage:
  python3 batch_indexer.py                          # Index all files in /opt/global-rag/kb/
  python3 batch_indexer.py --path /path/to/file      # Index single file
  python3 batch_indexer.py --rehash                   # Force re-index all files
  python3 batch_indexer.py --dry-run                  # Show what would be indexed
"""

import os
import sys
import hashlib
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

# Environment setup
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/opt/global-rag/cache/huggingface")
os.environ.setdefault("DOCLING_ARTIFACTS_PATH", "/opt/global-rag/cache/docling-models")

import weaviate
import weaviate.classes as wvc
from weaviate.auth import AuthApiKey
from FlagEmbedding import FlagModel
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult
from docling.document_converter import DocumentConverter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KB_ROOT = Path("/opt/global-rag/kb")
STATE_FILE = Path("/opt/global-rag/kb/.index_state.json")
LOG_FILE = Path("/opt/global-rag/logs/indexer.log")

# Chunking parameters
CHUNK_MAX_TOKENS = 512       # normal documents
CHUNK_OVERLAP_TOKENS = 64
CODE_MAX_TOKENS = 800
CODE_OVERLAP_TOKENS = 80

# Supported file extensions
SUPPORTED_FORMATS = {
    InputFormat.PDF,
    InputFormat.DOCX,
    InputFormat.PPTX,
    InputFormat.XLSX,
    InputFormat.MD,
    InputFormat.ASCIIDOC,
    InputFormat.HTML,
    InputFormat.IMAGE,
}

# Text-based formats that don't need Docling
TEXT_FORMATS = {".txt", ".md", ".markdown", ".asciidoc", ".html", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".rs", ".go", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOG_FILE.parent, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("batch_indexer")

# ---------------------------------------------------------------------------
# Index State Management (SHA-256 incremental)
# ---------------------------------------------------------------------------

@dataclass
class FileState:
    path: str
    hash: str
    chunk_count: int
    indexed_at: str

class IndexStateManager:
    """Track file indexing state for incremental updates."""

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self._states: dict[str, FileState] = {}
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                import json
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                for item in data:
                    self._states[item["path"]] = FileState(**item)
                log.info(f"Loaded {len(self._states)} previous index states")
            except Exception as e:
                log.warning(f"Failed to load index state: {e}, starting fresh")
                self._states = {}

    def save(self):
        import json
        data = [vars(s) for s in self._states.values()]
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get(self, path: str) -> Optional[FileState]:
        return self._states.get(path)

    def update(self, state: FileState):
        self._states[state.path] = state
        self.save()

    def remove(self, path: str):
        self._states.pop(path, None)
        self.save()

# ---------------------------------------------------------------------------
# File Hashing
# ---------------------------------------------------------------------------

def compute_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file for change detection."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()

# ---------------------------------------------------------------------------
# Text Chunking
# ---------------------------------------------------------------------------

def split_by_heading(text: str) -> list[tuple[str, str, str]]:
    """Split markdown-style text by heading levels, returning (title, heading, content)."""
    lines = text.split("\n")
    sections = []
    current_title = ""
    current_heading = ""
    current_content = []

    for line in lines:
        # Level 1 heading
        if line.startswith("# "):
            if current_content:
                sections.append((current_title, current_heading, "\n".join(current_content).strip()))
            current_title = line[2:].strip()
            current_heading = current_title
            current_content = []
        # Level 2 heading
        elif line.startswith("## "):
            if current_content:
                sections.append((current_title, current_heading, "\n".join(current_content).strip()))
            current_heading = line[3:].strip()
            current_content = []
        # Level 3+ heading
        elif line.startswith("###"):
            if current_content:
                sections.append((current_title, current_heading, "\n".join(current_content).strip()))
            current_heading = line.lstrip("# ").strip()
            current_content = []
        else:
            current_content.append(line)

    # Last section
    if current_content:
        sections.append((current_title, current_heading, "\n".join(current_content).strip()))

    return sections

def chunk_text(text: str, max_tokens: int = CHUNK_MAX_TOKENS,
               overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
               title: str = "", heading: str = "") -> list[dict]:
    """Split text into chunks respecting token limits (approximated by character count)."""
    # Approximate: 1 token ~ 1.5 Chinese chars or 1 English word
    avg_tokens_per_char = 0.6  # mixed language
    max_chars = int(max_tokens / avg_tokens_per_char)
    overlap_chars = int(overlap_tokens / avg_tokens_per_char)

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)
        # Try to break at sentence boundary
        if end < text_len:
            for sep in ["\n\n", "\n。", ". ", ".\n", "。\n", "\n"]:
                pos = text.rfind(sep, start + max_chars // 2, end)
                if pos > start:
                    end = pos + len(sep)
                    break

        chunk_text = text[start:end].strip()
        if chunk_text:
            # Combine with title/heading context
            full_content = f"{title} / {heading}\n{chunk_text}" if heading else chunk_text
            chunks.append({
                "content": chunk_text,
                "full_context": full_content,
                "title": title,
                "heading": heading,
                "page": 1,
                "chunk_index": len(chunks),
            })

        start = end - overlap_chars if end < text_len else end

    return chunks

# ---------------------------------------------------------------------------
# Document Parsing
# ---------------------------------------------------------------------------

def detect_mime_type(file_path: Path) -> str:
    """Detect MIME type from file extension."""
    ext = file_path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".py": "text/x-python",
        ".js": "text/javascript",
        ".ts": "text/typescript",
        ".java": "text/x-java",
        ".c": "text/x-c",
        ".cpp": "text/x-c++",
        ".rs": "text/x-rust",
        ".go": "text/x-go",
        ".json": "application/json",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".toml": "text/toml",
        ".html": "text/html",
        ".asciidoc": "text/asciidoc",
    }
    return mime_map.get(ext, "application/octet-stream")

def parse_text_file(file_path: Path) -> list[tuple[str, str, str]]:
    """Parse text-based files (markdown, code, etc.)."""
    ext = file_path.suffix.lower()
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        log.error(f"Failed to read {file_path}: {e}")
        return []

    # Markdown: split by headings
    if ext in {".md", ".markdown", ".asciidoc"}:
        sections = split_by_heading(content)
        return [(t, h, c) for t, h, c in sections if c.strip()]

    # Code files: split by function/class definitions
    if ext in {".py", ".js", ".ts", ".java", ".c", ".cpp", ".rs", ".go"}:
        return _split_code_file(content, ext, file_path.name)

    # Plain text: return as single block
    return [("", file_path.name, content)]

def _split_code_file(content: str, ext: str, filename: str) -> list[tuple[str, str, str]]:
    """Split code file by function/class boundaries."""
    sections = []
    lines = content.split("\n")
    current_section = []
    current_heading = ""
    current_title = filename

    # Patterns for function/class definitions
    patterns = {
        ".py": [r"^\s*def\s+\w+", r"^\s*class\s+\w+"],
        ".js": [r"^\s*(?:async\s+)?function\s+\w+", r"^\s*\w+\s*[:=]\s*(?:async\s+)?function",
                r"^\s*\w+\s*[:=]\s*\(.*\)\s*=>", r"^\s*class\s+\w+"],
        ".ts": [r"^\s*(?:export\s+)?(?:function|const|class)\s+\w+", r"^\s*\w+\s*[:=].*=>"],
        ".java": [r"^\s*(?:public|private|protected)\s+.*\s+\w+\s*\(", r"^\s*(?:public|private|protected)\s+class\s+"],
        ".c": [r"^[a-z_]+\s+\w+\s*\([^)]*\)\s*\{"],
        ".cpp": [r"^[a-z_]+\s+\w+\s*\([^)]*\)\s*\{"],
        ".rs": [r"^\s*(?:pub\s+)?fn\s+\w+", r"^\s*(?:impl|pub\s+impl)\s+.*for"],
        ".go": [r"^\s*func\s+\w+", r"^\s*type\s+\w+\s+struct"],
    }

    import re
    pats = patterns.get(ext, [])
    if not pats:
        return [("", filename, content)]

    compiled = [re.compile(p) for p in pats]

    for line in lines:
        for pat in compiled:
            if pat.match(line):
                # Save previous section
                if current_section:
                    text = "\n".join(current_section).strip()
                    if text:
                        sections.append((current_title, current_heading, text))
                current_section = [line]
                current_heading = line.strip()[:80]
                break
        else:
            current_section.append(line)

    # Last section
    if current_section:
        text = "\n".join(current_section).strip()
        if text:
            sections.append((current_title, current_heading, text))

    return sections if sections else [("", filename, content)]

def parse_with_docling(file_path: Path) -> list[tuple[str, str, str]]:
    """Parse PDF/Office documents with Docling."""
    try:
        converter = DocumentConverter()
        result: ConversionResult = converter.convert(str(file_path))

        doc = result.document
        markdown = doc.export_to_markdown()

        # Split by headings
        sections = split_by_heading(markdown)

        # Add page info (simplified — Docling page mapping is complex)
        for title, heading, content in sections:
            sections[sections.index((title, heading, content))] = (
                title, heading, content
            )

        return sections if sections else [("", file_path.name, markdown)]

    except Exception as e:
        log.error(f"Docling failed for {file_path}: {e}")
        return []

# ---------------------------------------------------------------------------
# Weaviate Operations
# ---------------------------------------------------------------------------

class WeaviateClient:
    """Weaviate client wrapper for KnowledgeChunk operations."""

    def __init__(self, api_key: str):
        self.client = weaviate.connect_to_local(
            host="localhost", port=8080, grpc_port=50051,
            auth_credentials=AuthApiKey(api_key),
        )
        self.collection = self.client.collections.get("KnowledgeChunk")
        self._ensure_schema()

    def _ensure_schema(self):
        """Verify KnowledgeChunk collection exists."""
        exists = self.client.collections.exists("KnowledgeChunk")
        if not exists:
            log.error("KnowledgeChunk collection not found. Run init_schema.py first.")
            sys.exit(1)
        log.info("KnowledgeChunk collection verified OK")

    def batch_insert(self, chunks: list[dict], source_hash: str,
                     source_path: str, source_name: str, mime_type: str, scope: str = "global"):
        """Insert chunks in batch mode with self-provided vectors."""
        if not chunks:
            return 0

        from FlagEmbedding import FlagModel
        # Lazy load model (already loaded by main process)
        # We receive model from caller to avoid re-loading

        inserted = 0
        errors = 0

        for i, chunk in enumerate(chunks):
            try:
                chunk_id = f"{'-'.join(hashlib.sha256(f'{source_path}:{source_hash}:{i}'.encode()).hexdigest()[:16].split(' '))}"
                chunk_id = f"idx-{hashlib.sha256(f'{source_path}:{source_hash}:{i}'.encode()).hexdigest()[:12]}"

                # Full context for vectorization
                search_text = chunk.get("full_context", chunk["content"])
                # Vector is provided by caller

                self.collection.data.insert(
                    properties={
                        "chunk_id": chunk_id,
                        "content": chunk["content"],
                        "title": chunk.get("title", source_name),
                        "heading": chunk.get("heading", ""),
                        "source_path": source_path,
                        "source_name": source_name,
                        "source_hash": source_hash,
                        "mime_type": mime_type,
                        "page": chunk.get("page", 1),
                        "chunk_index": i,
                        "scope": scope,
                        "modified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    # vector is provided by caller via vectors= parameter
                )
                inserted += 1
            except Exception as e:
                errors += 1
                log.warning(f"Failed to insert chunk {i} from {source_path}: {e}")

        return inserted, errors

    def delete_by_path(self, source_path: str):
        """Delete all chunks for a given source path."""
        try:
            import weaviate.classes as wvc2
            delete_filter = wvc2.query.Filter.by_property("source_path").equal(source_path)
            result = self.collection.data.delete_many(where=delete_filter)
            log.info(f"Deleted {result.deleted} chunks for {source_path}")
        except Exception as e:
            log.warning(f"Failed to delete chunks for {source_path}: {e}")

    def close(self):
        self.client.close()

# ---------------------------------------------------------------------------
# Batch Indexer
# ---------------------------------------------------------------------------

@dataclass
class IndexStats:
    total_files: int = 0
    skipped: int = 0
    indexed: int = 0
    failed: int = 0
    total_chunks: int = 0
    total_errors: int = 0
    elapsed_seconds: float = 0.0

def index_file(file_path: Path, model: FlagModel, weaviate_client: WeaviateClient,
               state_mgr: IndexStateManager, rehash: bool = False) -> tuple[int, int, int]:
    """Index a single file. Returns (inserted, errors, chunks_created)."""
    log.info(f"Processing: {file_path}")
    source_name = file_path.name
    source_path = str(file_path.resolve())
    mime_type = detect_mime_type(file_path)
    file_hash = compute_file_hash(file_path)

    # Check if file unchanged
    existing = None
    if not rehash:
        existing = state_mgr.get(source_path)
        if existing and existing.hash == file_hash:
            log.info(f"  SKIP (unchanged): hash={file_hash[:12]}... chunks={existing.chunk_count}")
            return 0, 0, 0

    # Delete old chunks if rehashing or if hash changed
    if existing:
        weaviate_client.delete_by_path(source_path)

    # Parse document
    ext = file_path.suffix.lower()
    if ext in TEXT_FORMATS:
        sections = parse_text_file(file_path)
    else:
        sections = parse_with_docling(file_path)

    if not sections:
        log.warning(f"  No content extracted from {file_path}")
        return 0, 0, 0

    # Determine chunking parameters
    is_code = ext in {".py", ".js", ".ts", ".java", ".c", ".cpp", ".rs", ".go"}
    max_tokens = CODE_MAX_TOKENS if is_code else CHUNK_MAX_TOKENS
    overlap_tokens = CODE_OVERLAP_TOKENS if is_code else CHUNK_OVERLAP_TOKENS

    # Create chunks
    all_chunks = []
    for title, heading, content in sections:
        if not content.strip():
            continue
        chunks = chunk_text(content, max_tokens, overlap_tokens, title, heading)
        for chunk in chunks:
            chunk["title"] = title or source_name
            all_chunks.append(chunk)

    if not all_chunks:
        log.warning(f"  No chunks created from {file_path}")
        return 0, 0, 0

    # Encode vectors
    log.info(f"  Encoding {len(all_chunks)} chunks with BGE-M3...")
    encode_start = time.time()
    for chunk in all_chunks:
        search_text = chunk.get("full_context", chunk["content"])
        chunk["vector"] = model.encode(search_text).tolist()

    encode_elapsed = time.time() - encode_start
    log.info(f"  Vector encoding done ({encode_elapsed:.1f}s)")

    # Batch insert into Weaviate
    log.info(f"  Inserting into Weaviate...")
    insert_start = time.time()

    # We need to use vectors= parameter for batch insert with self-provided vectors
    # Collect all vectors
    vectors = [chunk["vector"] for chunk in all_chunks]

    try:
        # Use batch insert with vectors
        for i, chunk in enumerate(all_chunks):
            chunk_id = f"idx-{hashlib.sha256(f'{source_path}:{file_hash}:{i}'.encode()).hexdigest()[:12]}"

            weaviate_client.collection.data.insert(
                properties={
                    "chunk_id": chunk_id,
                    "content": chunk["content"],
                    "title": chunk.get("title", source_name),
                    "heading": chunk.get("heading", ""),
                    "source_path": source_path,
                    "source_name": source_name,
                    "source_hash": file_hash,
                    "mime_type": mime_type,
                    "page": chunk.get("page", 1),
                    "chunk_index": i,
                    "scope": "global",
                    "modified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                vector=chunk["vector"],
            )

        insert_elapsed = time.time() - insert_start
        log.info(f"  Inserted {len(all_chunks)} chunks ({insert_elapsed:.1f}s)")

        # Update state
        state_mgr.update(FileState(
            path=source_path, hash=file_hash,
            chunk_count=len(all_chunks),
            indexed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ))

        return len(all_chunks), 0, len(all_chunks)

    except Exception as e:
        log.error(f"  Insert failed: {e}")
        elapsed = time.time() - insert_start
        return 0, 1, 0

def run_indexer(dry_run: bool = False, rehash: bool = False, single_path: Optional[str] = None):
    """Main indexer loop."""
    log.info("=" * 70)
    log.info("RAG Batch Indexer — Phase 2")
    log.info("=" * 70)
    log.info(f"KB Root: {KB_ROOT}")
    log.info(f"Rehash: {rehash}")
    log.info(f"Dry run: {dry_run}")

    stats = IndexStats()

    # Load model
    log.info("Loading BGE-M3 model...")
    model = FlagModel("BAAI/bge-m3", cpu="CPU", use_fp16=False)
    log.info("BGE-M3 loaded OK")

    # Load API key
    env_path = Path("/opt/global-rag/stack/.env")
    api_key = ""
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith("WEAVIATE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"')
                    break

    if not api_key:
        log.error("WEAVIATE_API_KEY not found in /opt/global-rag/stack/.env")
        sys.exit(1)

    # Connect Weaviate
    wvc_client = WeaviateClient(api_key)

    # Load state manager
    state_mgr = IndexStateManager()

    # Collect files
    if single_path:
        files = [Path(single_path)]
        for f in files:
            if not f.exists():
                log.error(f"File not found: {f}")
                sys.exit(1)
    else:
        files = sorted(KB_ROOT.rglob("*"))
        files = [f for f in files if f.is_file() and not f.name.startswith(".")]

    stats.total_files = len(files)
    log.info(f"Found {len(files)} files to process")

    if dry_run:
        for fp in files:
            file_hash = compute_file_hash(fp)
            existing = state_mgr.get(str(fp.resolve()))
            status = "SKIP" if existing and existing.hash == file_hash else "NEW"
            if existing and existing.hash != file_hash:
                status = "UPDATE"
            log.info(f"  [{status}] {fp} (hash={file_hash[:12]}...)")
        return stats

    # Process files
    start_time = time.time()

    for fp in files:
        try:
            chunks, errors, created = index_file(fp, model, wvc_client, state_mgr, rehash)
            stats.indexed += 1 if chunks > 0 else 0
            stats.skipped += 1 if chunks == 0 and errors == 0 else 0
            stats.failed += errors
            stats.total_chunks += chunks
            stats.total_errors += errors
        except Exception as e:
            stats.failed += 1
            stats.total_errors += 1
            log.error(f"  CRITICAL failure for {fp}: {e}")

    stats.elapsed_seconds = time.time() - start_time

    # Summary
    log.info("")
    log.info("=" * 70)
    log.info("INDEXING COMPLETE")
    log.info("=" * 70)
    log.info(f"  Total files:  {stats.total_files}")
    log.info(f"  Indexed:      {stats.indexed}")
    log.info(f"  Skipped:      {stats.skipped}")
    log.info(f"  Failed:       {stats.failed}")
    log.info(f"  Total chunks: {stats.total_chunks}")
    log.info(f"  Total errors: {stats.total_errors}")
    log.info(f"  Elapsed:      {stats.elapsed_seconds:.1f}s")
    log.info(f"  Rate:         {stats.total_chunks / max(stats.elapsed_seconds, 0.1):.1f} chunks/sec")
    log.info("=" * 70)

    wvc_client.close()
    return stats

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RAG Batch Indexer — Phase 2")
    parser.add_argument("--path", type=str, help="Index a single file path")
    parser.add_argument("--rehash", action="store_true", help="Force re-index all files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be indexed without indexing")
    args = parser.parse_args()

    stats = run_indexer(
        dry_run=args.dry_run,
        rehash=args.rehash,
        single_path=args.path,
    )

    sys.exit(1 if stats.failed > 0 or stats.total_errors > 0 else 0)

if __name__ == "__main__":
    main()