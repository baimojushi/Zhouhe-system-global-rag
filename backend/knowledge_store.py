#!/usr/bin/env python3
"""Persistent control-plane storage for Knowledge Workbench V2.

Weaviate remains the vector/search data plane.  This module owns stable
libraries, taxonomy nodes, documents, placements, ingest jobs, change sets and
audit records.  It deliberately uses only Python's standard library so the
Gateway can adopt V2 without adding another runtime service.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional


SCHEMA_VERSION = 3
LIBRARY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
MAX_JOB_RETRIES = 3
DEFAULT_LEASE_SECONDS = 300


DEFAULT_LIBRARIES: tuple[dict[str, str], ...] = (
    {
        "id": "ai-work",
        "name": "AI 工作记录",
        "collection_name": "kb_ai_work_v1",
        "kind": "document",
        "policy": "private · session-aware",
        "description": "保存模型实验、提示词版本、工作日志与可复用决策。",
    },
    {
        "id": "academic",
        "name": "学术资料",
        "collection_name": "kb_academic_v1",
        "kind": "document",
        "policy": "research · citation-first",
        "description": "强调作者、年份、DOI、版本和引用链。",
    },
    {
        "id": "production",
        "name": "生产文档",
        "collection_name": "kb_production_v1",
        "kind": "document",
        "policy": "team · recency-weighted",
        "description": "强调版本有效期、责任人、环境与变更记录。",
    },
    {
        "id": "notes",
        "name": "个人思维笔记",
        "collection_name": "kb_notes_v1",
        "kind": "document",
        "policy": "owner-only · exploratory",
        "description": "允许弱结构、交叉标签和持续生长的主题分支。",
    },
    {
        "id": "association",
        "name": "关联知识库",
        "collection_name": "kb_association_v1",
        "kind": "association",
        "policy": "edge-only · cross-library",
        "description": "保存跨库关系、证据指针和审核状态，不复制原文。",
    },
)


DEFAULT_TREES: dict[str, list[dict[str, Any]]] = {
    "ai-work": [
        {"node_id": "ai-unclassified", "name": "未归类", "description": "新文件入口", "is_unclassified": True},
        {"node_id": "ai-projects", "name": "项目", "description": "按项目组织", "children": [
            {"node_id": "ai-rag", "name": "Global RAG", "description": "全局检索系统", "children": [
                {"node_id": "ai-rag-design", "name": "设计决策", "description": "架构与产品决策"},
                {"node_id": "ai-rag-debug", "name": "调试记录", "description": "问题与验证过程"},
                {"node_id": "ai-rag-prompts", "name": "提示词版本", "description": "提示词及评测"},
            ]},
            {"node_id": "ai-agents", "name": "Agent 实验", "description": "智能体实验"},
            {"node_id": "ai-automation", "name": "自动化工作流", "description": "自动化与脚本"},
        ]},
        {"node_id": "ai-models", "name": "模型评测", "description": "模型对比与评测", "children": [
            {"node_id": "ai-closed", "name": "闭源 API", "description": "商业 API 模型评测"},
            {"node_id": "ai-local", "name": "本地模型", "description": "本地部署模型评测"},
        ]},
        {"node_id": "ai-decisions", "name": "跨项目决策", "description": "跨项目重大决策记录"},
    ],
    "academic": [
        {"node_id": "ac-unclassified", "name": "未归类", "description": "等待路由卡", "is_unclassified": True},
        {"node_id": "ac-cs", "name": "计算机科学", "description": "计算机科学各领域", "children": [
            {"node_id": "ac-ir", "name": "信息检索", "description": "IR 理论与系统", "children": [
                {"node_id": "ac-hybrid", "name": "混合检索", "description": "向量与关键词混合"},
                {"node_id": "ac-rerank", "name": "重排序", "description": "重排序模型与方法"},
            ]},
            {"node_id": "ac-llm", "name": "语言模型", "description": "LLM 架构与训练"},
            {"node_id": "ac-hci", "name": "人机交互", "description": "HCI 设计与评估"},
        ]},
        {"node_id": "ac-cog", "name": "认知科学", "description": "认知建模与实验"},
        {"node_id": "ac-method", "name": "研究方法", "description": "研究与方法论"},
    ],
    "production": [
        {"node_id": "pr-unclassified", "name": "未归类", "description": "需确认环境", "is_unclassified": True},
        {"node_id": "pr-platform", "name": "平台与基础设施", "description": "基础设施与平台", "children": [
            {"node_id": "pr-wsl", "name": "WSL2", "description": "Windows Subsystem for Linux"},
            {"node_id": "pr-llamacpp", "name": "llama.cpp / Gemma", "description": "llama.cpp 推理"},
            {"node_id": "pr-vector", "name": "向量数据库", "description": "Weaviate 与向量检索"},
        ]},
        {"node_id": "pr-sop", "name": "标准作业流程", "description": "SOP 与规范"},
        {"node_id": "pr-incidents", "name": "故障与复盘", "description": "故障记录与复盘", "children": [
            {"node_id": "pr-oom", "name": "GPU / OOM", "description": "显存与 OOM 问题"},
            {"node_id": "pr-index", "name": "索引异常", "description": "索引与检索异常"},
        ]},
        {"node_id": "pr-archive", "name": "历史版本", "description": "归档与历史"},
    ],
    "notes": [
        {"node_id": "nt-unclassified", "name": "未归类", "description": "允许长期停留", "is_unclassified": True},
        {"node_id": "nt-systems", "name": "系统与复杂性", "description": "复杂系统与涌现", "children": [
            {"node_id": "nt-emergence", "name": "涌现", "description": "涌现现象与理论"},
            {"node_id": "nt-feedback", "name": "反馈回路", "description": "反馈循环机制"},
        ]},
        {"node_id": "nt-making", "name": "创造与方法", "description": "创造方法论"},
        {"node_id": "nt-observation", "name": "观察记录", "description": "日常观察"},
        {"node_id": "nt-seeds", "name": "尚未成形的种子", "description": "早期想法"},
    ],
    "association": [
        {"node_id": "as-candidate", "name": "候选关联", "description": "等待人工确认", "is_unclassified": True},
        {"node_id": "as-support", "name": "相互支持", "description": "支持证据与跨域类比", "children": [
            {"node_id": "as-support-direct", "name": "直接证据", "description": "可直接验证的支持关系"},
            {"node_id": "as-support-analogy", "name": "跨域类比", "description": "不同领域的结构相似"},
        ]},
        {"node_id": "as-conflict", "name": "冲突与例外", "description": "结论或适用条件冲突", "children": [
            {"node_id": "as-version", "name": "版本冲突", "description": "新旧版本不一致"},
            {"node_id": "as-counter", "name": "反例", "description": "反对证据"},
        ]},
        {"node_id": "as-causal", "name": "因果与条件", "description": "因果、影响和成立条件"},
        {"node_id": "as-counterintuitive", "name": "反直觉假设", "description": "尚待验证的跨库结论"},
    ],
}


class StoreError(RuntimeError):
    """Base class for control-plane failures."""


class StoreNotFound(StoreError):
    pass


class StoreConflict(StoreError):
    pass


class StoreValidationError(StoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _row_dict(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = int(base64.urlsafe_b64decode(padded).decode("ascii"))
        return max(value, 0)
    except (ValueError, UnicodeDecodeError):
        raise StoreValidationError("invalid cursor")


class KnowledgeStore:
    """SQLite-backed V2 knowledge management repository."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._init_lock:
            # SQLite does not allow changing journal mode from inside an
            # active transaction when an existing database is reopened.
            pragma_conn = self._connect()
            try:
                pragma_conn.execute("PRAGMA journal_mode = WAL")
            finally:
                pragma_conn.close()
            with self._transaction() as conn:
                conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS libraries (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    collection_name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL DEFAULT 'document',
                    policy TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    taxonomy_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS taxonomy_nodes (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    parent_id TEXT REFERENCES taxonomy_nodes(id),
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT 'physical',
                    is_unclassified INTEGER NOT NULL DEFAULT 0,
                    locked INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_library_parent
                    ON taxonomy_nodes(library_id, parent_id, status, position);

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    title TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    source_path TEXT NOT NULL DEFAULT '',
                    source_name TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unclassified',
                    index_status TEXT NOT NULL DEFAULT 'pending',
                    owner TEXT NOT NULL DEFAULT 'local-owner',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    current_version_id TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_library_status
                    ON documents(library_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_documents_source
                    ON documents(library_id, source_path, content_hash);

                CREATE TABLE IF NOT EXISTS document_versions (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    content_hash TEXT NOT NULL DEFAULT '',
                    source_uri TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    parser_version TEXT NOT NULL DEFAULT '',
                    index_status TEXT NOT NULL DEFAULT 'pending',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    weaviate_collection TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, version_number)
                );
                CREATE INDEX IF NOT EXISTS idx_versions_document
                    ON document_versions(document_id, version_number DESC);

                CREATE TABLE IF NOT EXISTS document_placements (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                    placement_type TEXT NOT NULL CHECK(placement_type IN ('PRIMARY', 'ALIAS')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, node_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_document_primary_placement
                    ON document_placements(document_id) WHERE placement_type = 'PRIMARY';
                CREATE INDEX IF NOT EXISTS idx_placements_node
                    ON document_placements(node_id, placement_type);

                CREATE TABLE IF NOT EXISTS tags (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    name TEXT NOT NULL,
                    color TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(library_id, name)
                );

                CREATE TABLE IF NOT EXISTS document_tags (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, tag_id)
                );

                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    target_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                    source_path TEXT NOT NULL,
                    document_id TEXT REFERENCES documents(id),
                    version_id TEXT REFERENCES document_versions(id),
                    state TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    worker_id TEXT NOT NULL DEFAULT '',
                    lease_until TEXT NOT NULL DEFAULT '',
                    chunks_indexed INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON ingest_jobs(state, created_at);

                CREATE TABLE IF NOT EXISTS change_sets (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    base_version INTEGER NOT NULL,
                    applied_version INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'applied',
                    actor TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    operations_json TEXT NOT NULL,
                    inverse_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS classification_proposals (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL REFERENCES libraries(id),
                    status TEXT NOT NULL DEFAULT 'draft',
                    llm_model TEXT NOT NULL DEFAULT '',
                    llm_response_json TEXT NOT NULL DEFAULT '{}',
                    routing_cards_json TEXT NOT NULL DEFAULT '[]',
                    subtree_json TEXT NOT NULL DEFAULT '[]',
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT 'auto-classifier',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proposals_library_status
                    ON classification_proposals(library_id, status);

                CREATE TABLE IF NOT EXISTS proposal_items (
                    id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL REFERENCES classification_proposals(id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    version_id TEXT NOT NULL DEFAULT '' REFERENCES document_versions(id),
                    source_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                    target_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                    status TEXT NOT NULL DEFAULT 'pending',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    reason_code TEXT NOT NULL DEFAULT '',
                    llm_reasoning TEXT NOT NULL DEFAULT '',
                    previous_node_id TEXT NOT NULL DEFAULT '',
                    applied_at TEXT NOT NULL DEFAULT '',
                    reverted_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proposal_items_proposal
                    ON proposal_items(proposal_id, status);
                CREATE INDEX IF NOT EXISTS idx_proposal_items_document
                    ON proposal_items(document_id);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    library_id TEXT NOT NULL,
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    trace_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_library_time
                    ON audit_events(library_id, created_at DESC);
                """
            )
                self._migrate_schema(conn)
                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                self._seed_defaults(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Migrate existing schema to current version."""
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        current_version = int(row["value"]) if row else 0

        if current_version < 2:
            # Add worker lease columns to ingest_jobs
            columns = [
                col["name"] for col in conn.execute(
                    "PRAGMA table_info(ingest_jobs)"
                ).fetchall()
            ]
            if "worker_id" not in columns:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN worker_id TEXT NOT NULL DEFAULT ''"
                )
            if "lease_until" not in columns:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN lease_until TEXT NOT NULL DEFAULT ''"
                )
            if "max_retries" not in columns:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3"
                )
            if "chunks_indexed" not in columns:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN chunks_indexed INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_lease ON ingest_jobs(state, lease_until)"
            )

        if current_version < 3:
            # V3: Add version_id to ingest_jobs and version indexing columns to document_versions
            job_columns = [
                col["name"] for col in conn.execute(
                    "PRAGMA table_info(ingest_jobs)"
                ).fetchall()
            ]
            if "version_id" not in job_columns:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN version_id TEXT REFERENCES document_versions(id) DEFAULT ''"
                )

            ver_columns = [
                col["name"] for col in conn.execute(
                    "PRAGMA table_info(document_versions)"
                ).fetchall()
            ]
            if "index_status" not in ver_columns:
                conn.execute(
                    "ALTER TABLE document_versions ADD COLUMN index_status TEXT NOT NULL DEFAULT 'pending'"
                )
            if "chunk_count" not in ver_columns:
                conn.execute(
                    "ALTER TABLE document_versions ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0"
                )
            if "weaviate_collection" not in ver_columns:
                conn.execute(
                    "ALTER TABLE document_versions ADD COLUMN weaviate_collection TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id, version_number DESC)"
            )

        # V4: Add classification proposals tables (idempotent CREATE IF NOT EXISTS)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS classification_proposals (
                id TEXT PRIMARY KEY,
                library_id TEXT NOT NULL REFERENCES libraries(id),
                status TEXT NOT NULL DEFAULT 'draft',
                llm_model TEXT NOT NULL DEFAULT '',
                llm_response_json TEXT NOT NULL DEFAULT '{}',
                routing_cards_json TEXT NOT NULL DEFAULT '[]',
                subtree_json TEXT NOT NULL DEFAULT '[]',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL DEFAULT 'auto-classifier',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proposals_library_status
                ON classification_proposals(library_id, status);

            CREATE TABLE IF NOT EXISTS proposal_items (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL REFERENCES classification_proposals(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES documents(id),
                version_id TEXT NOT NULL DEFAULT '' REFERENCES document_versions(id),
                source_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                target_node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL NOT NULL DEFAULT 0.0,
                reason_code TEXT NOT NULL DEFAULT '',
                llm_reasoning TEXT NOT NULL DEFAULT '',
                previous_node_id TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT '',
                reverted_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proposal_items_proposal
                ON proposal_items(proposal_id, status);
            CREATE INDEX IF NOT EXISTS idx_proposal_items_document
                ON proposal_items(document_id);
        """)

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        now = utc_now()
        for library in DEFAULT_LIBRARIES:
            conn.execute(
                """INSERT OR IGNORE INTO libraries
                   (id, name, collection_name, kind, policy, description, status,
                    taxonomy_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)""",
                (
                    library["id"], library["name"], library["collection_name"],
                    library["kind"], library["policy"], library["description"],
                    now, now,
                ),
            )
            existing = conn.execute(
                "SELECT COUNT(*) AS total FROM taxonomy_nodes WHERE library_id = ?",
                (library["id"],),
            ).fetchone()["total"]
            if existing == 0:
                self._seed_tree(conn, library["id"], DEFAULT_TREES[library["id"]], None)

    def _seed_tree(
        self,
        conn: sqlite3.Connection,
        library_id: str,
        nodes: list[dict[str, Any]],
        parent_id: Optional[str],
    ) -> None:
        now = utc_now()
        for position, node in enumerate(nodes):
            conn.execute(
                """INSERT INTO taxonomy_nodes
                   (id, library_id, parent_id, name, description, position, kind,
                    is_unclassified, locked, status, revision, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'physical', ?, ?, 'active', 1, ?, ?)""",
                (
                    node["node_id"], library_id, parent_id, node["name"],
                    node.get("description", ""), position,
                    int(bool(node.get("is_unclassified"))),
                    int(bool(node.get("is_unclassified"))), now, now,
                ),
            )
            self._seed_tree(conn, library_id, node.get("children", []), node["node_id"])

    @staticmethod
    def _require_library(conn: sqlite3.Connection, library_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if row is None:
            raise StoreNotFound(f"library '{library_id}' not found")
        return row

    @staticmethod
    def _require_node(conn: sqlite3.Connection, node_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM taxonomy_nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise StoreNotFound(f"node '{node_id}' not found")
        return row

    @staticmethod
    def _require_document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise StoreNotFound(f"document '{document_id}' not found")
        return row

    @staticmethod
    def _check_version(library: sqlite3.Row, expected_version: Optional[int]) -> None:
        if expected_version is not None and library["taxonomy_version"] != expected_version:
            raise StoreConflict(
                f"taxonomy_version_conflict: expected {expected_version}, "
                f"got {library['taxonomy_version']}"
            )

    @staticmethod
    def _bump_version(conn: sqlite3.Connection, library_id: str) -> tuple[int, int]:
        row = conn.execute(
            "SELECT taxonomy_version FROM libraries WHERE id = ?", (library_id,)
        ).fetchone()
        before = row["taxonomy_version"]
        after = before + 1
        conn.execute(
            "UPDATE libraries SET taxonomy_version = ?, updated_at = ? WHERE id = ?",
            (after, utc_now(), library_id),
        )
        return before, after

    @staticmethod
    def _record_change(
        conn: sqlite3.Connection,
        library_id: str,
        base_version: int,
        applied_version: int,
        actor: str,
        summary: str,
        operation: dict[str, Any],
        inverse: dict[str, Any],
        target_type: str,
        target_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> str:
        change_id = new_id("change")
        now = utc_now()
        conn.execute(
            """INSERT INTO change_sets
               (id, library_id, base_version, applied_version, state, actor, summary,
                operations_json, inverse_json, created_at)
               VALUES (?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?)""",
            (
                change_id, library_id, base_version, applied_version, actor, summary,
                json.dumps(operation, ensure_ascii=False),
                json.dumps(inverse, ensure_ascii=False), now,
            ),
        )
        conn.execute(
            """INSERT INTO audit_events
               (id, actor, action, target_type, target_id, library_id,
                before_json, after_json, trace_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id("audit"), actor, operation.get("op", "update"), target_type,
                target_id, library_id,
                json.dumps(before or {}, ensure_ascii=False),
                json.dumps(after or {}, ensure_ascii=False), change_id, now,
            ),
        )
        return change_id

    def list_libraries(self, include_archived: bool = False) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            where = "" if include_archived else "WHERE l.status = 'active'"
            rows = conn.execute(
                f"""SELECT l.*,
                       (SELECT COUNT(*) FROM documents d
                        WHERE d.library_id = l.id AND d.status != 'trash') AS document_count,
                       (SELECT COUNT(*) FROM documents d
                        JOIN document_placements p ON p.document_id = d.id
                        JOIN taxonomy_nodes n ON n.id = p.node_id
                        WHERE d.library_id = l.id AND d.status != 'trash'
                          AND p.placement_type = 'PRIMARY' AND n.is_unclassified = 1) AS unclassified_count
                    FROM libraries l {where}
                    ORDER BY l.created_at, l.id"""
            ).fetchall()
            return [self._library_payload(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _library_payload(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        return {
            **data,
            "library_id": data["id"],
            "collection": data["collection_name"],
            "count": data.get("document_count", 0),
            "unclassified": data.get("unclassified_count", 0),
        }

    def create_library(
        self,
        name: str,
        library_id: Optional[str] = None,
        kind: str = "document",
        policy: str = "private · manual-first",
        description: str = "",
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise StoreValidationError("library name is required")
        library_id = (library_id or f"lib-{uuid.uuid4().hex[:10]}").strip().lower()
        if not LIBRARY_ID_RE.fullmatch(library_id):
            raise StoreValidationError("library_id must contain lowercase letters, numbers or hyphens")
        if kind not in {"document", "association"}:
            raise StoreValidationError("kind must be 'document' or 'association'")
        collection = f"kb_{library_id.replace('-', '_')}_v1"
        now = utc_now()
        with self._transaction() as conn:
            try:
                conn.execute(
                    """INSERT INTO libraries
                       (id, name, collection_name, kind, policy, description, status,
                        taxonomy_version, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)""",
                    (library_id, name, collection, kind, policy.strip(), description.strip(), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(f"library '{library_id}' already exists") from exc
            unclassified_id = f"{library_id}-unclassified"
            conn.execute(
                """INSERT INTO taxonomy_nodes
                   (id, library_id, parent_id, name, description, position, kind,
                    is_unclassified, locked, status, revision, created_at, updated_at)
                   VALUES (?, ?, NULL, '未归类', '新文件入口', 0, 'physical',
                           1, 1, 'active', 1, ?, ?)""",
                (unclassified_id, library_id, now, now),
            )
            self._record_change(
                conn, library_id, 0, 1, actor, f"创建知识库 {name}",
                {"op": "CREATE_LIBRARY", "library_id": library_id},
                {"op": "ARCHIVE_LIBRARY", "library_id": library_id},
                "library", library_id, after={"name": name, "kind": kind},
            )
        return next(item for item in self.list_libraries(True) if item["id"] == library_id)

    def update_library(
        self,
        library_id: str,
        fields: dict[str, Any],
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        allowed = {"name", "description", "policy", "status"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            raise StoreValidationError("no supported library fields supplied")
        if "status" in updates and updates["status"] not in {"active", "archived"}:
            raise StoreValidationError("library status must be active or archived")
        with self._transaction() as conn:
            before = dict(self._require_library(conn, library_id))
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE libraries SET {assignments}, updated_at = ? WHERE id = ?",
                (*updates.values(), utc_now(), library_id),
            )
            after = dict(self._require_library(conn, library_id))
            self._record_change(
                conn, library_id, before["taxonomy_version"], before["taxonomy_version"],
                actor, f"更新知识库 {before['name']}",
                {"op": "UPDATE_LIBRARY", "library_id": library_id, "fields": updates},
                {"op": "UPDATE_LIBRARY", "library_id": library_id,
                 "fields": {key: before[key] for key in updates}},
                "library", library_id, before, after,
            )
        return next(item for item in self.list_libraries(True) if item["id"] == library_id)

    def get_tree(self, library_id: str, include_archived: bool = False) -> dict[str, Any]:
        conn = self._connect()
        try:
            library = self._require_library(conn, library_id)
            status_where = "" if include_archived else "AND n.status = 'active'"
            rows = conn.execute(
                f"""SELECT n.*,
                       (SELECT COUNT(*) FROM document_placements p
                        JOIN documents d ON d.id = p.document_id
                        WHERE p.node_id = n.id AND p.placement_type = 'PRIMARY'
                          AND d.status != 'trash') AS direct_count
                    FROM taxonomy_nodes n
                    WHERE n.library_id = ? {status_where}
                    ORDER BY n.position, lower(n.name), n.id""",
                (library_id,),
            ).fetchall()
            by_id: dict[str, dict[str, Any]] = {}
            roots: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item.update({
                    "node_id": item["id"],
                    "label": item["name"],
                    "hint": item["description"],
                    "count": item["direct_count"],
                    "children": [],
                    "is_unclassified": bool(item["is_unclassified"]),
                    "locked": bool(item["locked"]),
                })
                by_id[item["id"]] = item
            for item in by_id.values():
                parent = by_id.get(item["parent_id"])
                if parent is None:
                    roots.append(item)
                else:
                    parent["children"].append(item)

            def count_subtree(node: dict[str, Any]) -> int:
                total = node["direct_count"]
                for child in node["children"]:
                    total += count_subtree(child)
                node["subtree_count"] = total
                node["count"] = total
                return total

            for root in roots:
                count_subtree(root)
            return {
                "library_id": library_id,
                "version": library["taxonomy_version"],
                "tree": roots,
            }
        finally:
            conn.close()

    def create_node(
        self,
        library_id: str,
        name: str,
        parent_id: Optional[str] = None,
        description: str = "",
        kind: str = "physical",
        expected_version: Optional[int] = None,
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise StoreValidationError("node name is required")
        if len(name) > 120:
            raise StoreValidationError("node name is too long")
        if kind not in {"physical", "smart", "alias"}:
            raise StoreValidationError("unsupported node kind")
        node_id = new_id("node")
        now = utc_now()
        with self._transaction() as conn:
            library = self._require_library(conn, library_id)
            self._check_version(library, expected_version)
            if parent_id:
                parent = self._require_node(conn, parent_id)
                if parent["library_id"] != library_id or parent["status"] != "active":
                    raise StoreValidationError("parent node does not belong to the active library")
            duplicate = conn.execute(
                """SELECT 1 FROM taxonomy_nodes
                   WHERE library_id = ? AND parent_id IS ? AND lower(name) = lower(?)
                     AND status = 'active'""",
                (library_id, parent_id, name),
            ).fetchone()
            if duplicate:
                raise StoreConflict(f"node '{name}' already exists at this level")
            position = conn.execute(
                """SELECT COALESCE(MAX(position), -1) + 1 AS next_position
                   FROM taxonomy_nodes WHERE library_id = ? AND parent_id IS ?""",
                (library_id, parent_id),
            ).fetchone()["next_position"]
            conn.execute(
                """INSERT INTO taxonomy_nodes
                   (id, library_id, parent_id, name, description, position, kind,
                    is_unclassified, locked, status, revision, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'active', 1, ?, ?)""",
                (node_id, library_id, parent_id, name, description.strip(), position, kind, now, now),
            )
            base, applied = self._bump_version(conn, library_id)
            self._record_change(
                conn, library_id, base, applied, actor, f"创建目录 {name}",
                {"op": "CREATE_NODE", "node_id": node_id, "parent_id": parent_id},
                {"op": "ARCHIVE_NODE", "node_id": node_id},
                "taxonomy_node", node_id, after={"name": name, "parent_id": parent_id},
            )
            return dict(self._require_node(conn, node_id)) | {"taxonomy_version": applied}

    def update_node(
        self,
        node_id: str,
        fields: dict[str, Any],
        expected_version: Optional[int] = None,
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        allowed = {"name", "description", "locked", "kind"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            raise StoreValidationError("no supported node fields supplied")
        if "name" in updates:
            updates["name"] = str(updates["name"]).strip()
            if not updates["name"]:
                raise StoreValidationError("node name is required")
        if "kind" in updates and updates["kind"] not in {"physical", "smart", "alias"}:
            raise StoreValidationError("unsupported node kind")
        if "locked" in updates:
            updates["locked"] = int(bool(updates["locked"]))
        with self._transaction() as conn:
            before = dict(self._require_node(conn, node_id))
            library = self._require_library(conn, before["library_id"])
            self._check_version(library, expected_version)
            if before["is_unclassified"] and updates.get("kind", before["kind"]) != "physical":
                raise StoreValidationError("unclassified node must remain physical")
            if "name" in updates:
                duplicate = conn.execute(
                    """SELECT 1 FROM taxonomy_nodes WHERE library_id = ? AND parent_id IS ?
                       AND lower(name) = lower(?) AND id != ? AND status = 'active'""",
                    (before["library_id"], before["parent_id"], updates["name"], node_id),
                ).fetchone()
                if duplicate:
                    raise StoreConflict(f"node '{updates['name']}' already exists at this level")
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE taxonomy_nodes SET {assignments}, revision = revision + 1, updated_at = ? WHERE id = ?",
                (*updates.values(), utc_now(), node_id),
            )
            base, applied = self._bump_version(conn, before["library_id"])
            after = dict(self._require_node(conn, node_id))
            self._record_change(
                conn, before["library_id"], base, applied, actor, f"更新目录 {before['name']}",
                {"op": "UPDATE_NODE", "node_id": node_id, "fields": updates},
                {"op": "UPDATE_NODE", "node_id": node_id,
                 "fields": {key: before[key] for key in updates}},
                "taxonomy_node", node_id, before, after,
            )
            return after | {"taxonomy_version": applied}

    def move_node(
        self,
        node_id: str,
        new_parent_id: Optional[str],
        position: Optional[int] = None,
        expected_version: Optional[int] = None,
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        with self._transaction() as conn:
            before = dict(self._require_node(conn, node_id))
            if before["is_unclassified"]:
                raise StoreValidationError("unclassified node cannot be moved")
            library = self._require_library(conn, before["library_id"])
            self._check_version(library, expected_version)
            if new_parent_id == node_id:
                raise StoreValidationError("node cannot be its own parent")
            if new_parent_id:
                parent = self._require_node(conn, new_parent_id)
                if parent["library_id"] != before["library_id"] or parent["status"] != "active":
                    raise StoreValidationError("target parent is outside the active library")
                descendant = conn.execute(
                    """WITH RECURSIVE descendants(id) AS (
                           SELECT id FROM taxonomy_nodes WHERE parent_id = ?
                           UNION ALL
                           SELECT n.id FROM taxonomy_nodes n JOIN descendants d ON n.parent_id = d.id
                       ) SELECT 1 FROM descendants WHERE id = ? LIMIT 1""",
                    (node_id, new_parent_id),
                ).fetchone()
                if descendant:
                    raise StoreValidationError("node cannot be moved into its descendant")
            if position is None:
                position = conn.execute(
                    """SELECT COALESCE(MAX(position), -1) + 1 AS next_position
                       FROM taxonomy_nodes WHERE library_id = ? AND parent_id IS ?""",
                    (before["library_id"], new_parent_id),
                ).fetchone()["next_position"]
            position = max(int(position), 0)
            conn.execute(
                """UPDATE taxonomy_nodes SET parent_id = ?, position = ?, revision = revision + 1,
                   updated_at = ? WHERE id = ?""",
                (new_parent_id, position, utc_now(), node_id),
            )
            base, applied = self._bump_version(conn, before["library_id"])
            after = dict(self._require_node(conn, node_id))
            self._record_change(
                conn, before["library_id"], base, applied, actor, f"移动目录 {before['name']}",
                {"op": "MOVE_NODE", "node_id": node_id, "parent_id": new_parent_id, "position": position},
                {"op": "MOVE_NODE", "node_id": node_id, "parent_id": before["parent_id"],
                 "position": before["position"]},
                "taxonomy_node", node_id, before, after,
            )
            return after | {"taxonomy_version": applied}

    def archive_node(
        self,
        node_id: str,
        expected_version: Optional[int] = None,
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        """Archive a branch and safely move its primary documents to Unclassified."""
        with self._transaction() as conn:
            node = dict(self._require_node(conn, node_id))
            if node["is_unclassified"]:
                raise StoreValidationError("unclassified node cannot be archived")
            library = self._require_library(conn, node["library_id"])
            self._check_version(library, expected_version)
            unclassified = conn.execute(
                "SELECT id FROM taxonomy_nodes WHERE library_id = ? AND is_unclassified = 1 AND status = 'active'",
                (node["library_id"],),
            ).fetchone()
            subtree_rows = conn.execute(
                """WITH RECURSIVE subtree(id) AS (
                       SELECT ? UNION ALL
                       SELECT n.id FROM taxonomy_nodes n JOIN subtree s ON n.parent_id = s.id
                   ) SELECT id FROM subtree""",
                (node_id,),
            ).fetchall()
            subtree_ids = [row["id"] for row in subtree_rows]
            placeholders = ",".join("?" for _ in subtree_ids)
            docs = conn.execute(
                f"""SELECT document_id FROM document_placements
                    WHERE placement_type = 'PRIMARY' AND node_id IN ({placeholders})""",
                subtree_ids,
            ).fetchall()
            for row in docs:
                conn.execute(
                    "DELETE FROM document_placements WHERE document_id = ? AND placement_type = 'PRIMARY'",
                    (row["document_id"],),
                )
                conn.execute(
                    """INSERT INTO document_placements(document_id, node_id, placement_type, created_at)
                       VALUES (?, ?, 'PRIMARY', ?)""",
                    (row["document_id"], unclassified["id"], utc_now()),
                )
                conn.execute(
                    "UPDATE documents SET status = 'unclassified', revision = revision + 1, updated_at = ? WHERE id = ?",
                    (utc_now(), row["document_id"]),
                )
            conn.execute(
                f"UPDATE taxonomy_nodes SET status = 'archived', revision = revision + 1, updated_at = ? WHERE id IN ({placeholders})",
                (utc_now(), *subtree_ids),
            )
            base, applied = self._bump_version(conn, node["library_id"])
            change_id = self._record_change(
                conn, node["library_id"], base, applied, actor, f"归档目录 {node['name']}",
                {"op": "ARCHIVE_NODE", "node_id": node_id, "moved_documents": len(docs)},
                {"op": "RESTORE_NODE", "node_id": node_id},
                "taxonomy_node", node_id, node, {"status": "archived"},
            )
            return {
                "node_id": node_id,
                "status": "archived",
                "archived_nodes": len(subtree_ids),
                "moved_documents": len(docs),
                "taxonomy_version": applied,
                "change_set_id": change_id,
            }

    def list_documents(
        self,
        library_id: str,
        node_id: Optional[str] = None,
        query: str = "",
        status: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        limit = min(max(int(limit), 1), 200)
        offset = _decode_cursor(cursor)
        conn = self._connect()
        try:
            self._require_library(conn, library_id)
            params: list[Any] = [library_id]
            where = ["d.library_id = ?", "d.status != 'trash'"]
            join = """LEFT JOIN document_placements primary_place
                       ON primary_place.document_id = d.id AND primary_place.placement_type = 'PRIMARY'
                      LEFT JOIN taxonomy_nodes primary_node ON primary_node.id = primary_place.node_id"""
            if node_id:
                node = self._require_node(conn, node_id)
                if node["library_id"] != library_id:
                    raise StoreValidationError("node does not belong to library")
                where.append(
                    """primary_place.node_id IN (
                         WITH RECURSIVE subtree(id) AS (
                           SELECT ? UNION ALL
                           SELECT n.id FROM taxonomy_nodes n JOIN subtree s ON n.parent_id = s.id
                         ) SELECT id FROM subtree
                       )"""
                )
                params.append(node_id)
            if query.strip():
                where.append("(lower(d.title) LIKE lower(?) OR lower(d.source_name) LIKE lower(?))")
                pattern = f"%{query.strip()}%"
                params.extend([pattern, pattern])
            if status:
                where.append("d.status = ?")
                params.append(status)
            params.extend([limit + 1, offset])
            rows = conn.execute(
                f"""SELECT d.*, primary_node.id AS primary_node_id,
                           primary_node.name AS primary_node_name
                    FROM documents d {join}
                    WHERE {' AND '.join(where)}
                    ORDER BY d.updated_at DESC, d.id
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            items = [self._document_payload(conn, row) for row in rows]
            return {
                "items": items,
                "count": len(items),
                "next_cursor": _encode_cursor(offset + limit) if has_more else None,
            }
        finally:
            conn.close()

    @staticmethod
    def _document_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["metadata"] = json.loads(data.pop("metadata_json", "{}") or "{}")
        except json.JSONDecodeError:
            data["metadata"] = {}
        tags = conn.execute(
            """SELECT t.id, t.name, t.color FROM tags t
               JOIN document_tags dt ON dt.tag_id = t.id
               WHERE dt.document_id = ? ORDER BY lower(t.name)""",
            (data["id"],),
        ).fetchall()
        aliases = conn.execute(
            """SELECT n.id, n.name FROM taxonomy_nodes n
               JOIN document_placements p ON p.node_id = n.id
               WHERE p.document_id = ? AND p.placement_type = 'ALIAS'
               ORDER BY lower(n.name)""",
            (data["id"],),
        ).fetchall()
        data["tags"] = [dict(item) for item in tags]
        data["aliases"] = [dict(item) for item in aliases]
        return data

    def get_document(self, document_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            self._require_document(conn, document_id)
            row = conn.execute(
                """SELECT d.*, n.id AS primary_node_id, n.name AS primary_node_name
                   FROM documents d
                   LEFT JOIN document_placements p ON p.document_id = d.id AND p.placement_type = 'PRIMARY'
                   LEFT JOIN taxonomy_nodes n ON n.id = p.node_id
                   WHERE d.id = ?""",
                (document_id,),
            ).fetchone()
            result = self._document_payload(conn, row)
            result["versions"] = [dict(item) for item in conn.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_number DESC",
                (document_id,),
            ).fetchall()]
            return result
        finally:
            conn.close()

    def create_document(
        self,
        library_id: str,
        title: str,
        node_id: str,
        mime_type: str = "application/octet-stream",
        source_path: str = "",
        source_name: str = "",
        content_hash: str = "",
        size_bytes: int = 0,
        index_status: str = "pending",
        actor: str = "local-owner",
        idempotent: bool = False,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise StoreValidationError("document title is required")
        with self._transaction() as conn:
            self._require_library(conn, library_id)
            node = self._require_node(conn, node_id)
            if node["library_id"] != library_id or node["status"] != "active":
                raise StoreValidationError("target node does not belong to the active library")
            if idempotent and source_path:
                existing = conn.execute(
                    """SELECT id FROM documents WHERE library_id = ? AND source_path = ?
                       AND content_hash = ? AND status != 'trash' LIMIT 1""",
                    (library_id, source_path, content_hash),
                ).fetchone()
                if existing:
                    return self.get_document(existing["id"])
            document_id = new_id("doc")
            version_id = new_id("version")
            now = utc_now()
            status = "unclassified" if node["is_unclassified"] else "active"
            conn.execute(
                """INSERT INTO documents
                   (id, library_id, title, mime_type, source_path, source_name,
                    content_hash, status, index_status, owner, metadata_json,
                    current_version_id, revision, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'local-owner', '{}', ?, 1, ?, ?)""",
                (
                    document_id, library_id, title, mime_type, source_path,
                    source_name or Path(source_path).name, content_hash, status,
                    index_status, version_id, now, now,
                ),
            )
            conn.execute(
                """INSERT INTO document_versions
                   (id, document_id, version_number, content_hash, source_uri,
                    size_bytes, parser_version, created_at)
                   VALUES (?, ?, 1, ?, ?, ?, '', ?)""",
                (version_id, document_id, content_hash, source_path, max(size_bytes, 0), now),
            )
            conn.execute(
                """INSERT INTO document_placements(document_id, node_id, placement_type, created_at)
                   VALUES (?, ?, 'PRIMARY', ?)""",
                (document_id, node_id, now),
            )
            library = self._require_library(conn, library_id)
            self._record_change(
                conn, library_id, library["taxonomy_version"], library["taxonomy_version"],
                actor, f"创建文档 {title}",
                {"op": "CREATE_DOCUMENT", "document_id": document_id, "node_id": node_id},
                {"op": "TRASH_DOCUMENT", "document_id": document_id},
                "document", document_id, after={"title": title, "node_id": node_id},
            )
        return self.get_document(document_id)

    def update_document(
        self,
        document_id: str,
        fields: dict[str, Any],
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        allowed = {"title", "status", "index_status", "owner", "metadata"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            raise StoreValidationError("no supported document fields supplied")
        if "title" in updates:
            updates["title"] = str(updates["title"]).strip()
            if not updates["title"]:
                raise StoreValidationError("document title is required")
        if "status" in updates and updates["status"] not in {
            "unclassified", "active", "archived", "trash"
        }:
            raise StoreValidationError("unsupported document status")
        if "metadata" in updates:
            updates["metadata_json"] = json.dumps(updates.pop("metadata"), ensure_ascii=False)
        with self._transaction() as conn:
            before = dict(self._require_document(conn, document_id))
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE documents SET {assignments}, revision = revision + 1, updated_at = ? WHERE id = ?",
                (*updates.values(), utc_now(), document_id),
            )
            after = dict(self._require_document(conn, document_id))
            library = self._require_library(conn, before["library_id"])
            self._record_change(
                conn, before["library_id"], library["taxonomy_version"], library["taxonomy_version"],
                actor, f"更新文档 {before['title']}",
                {"op": "UPDATE_DOCUMENT", "document_id": document_id, "fields": updates},
                {"op": "UPDATE_DOCUMENT", "document_id": document_id,
                 "fields": {key: before[key] for key in updates}},
                "document", document_id, before, after,
            )
        return self.get_document(document_id)

    def move_documents(
        self,
        document_ids: list[str],
        target_node_id: str,
        actor: str = "local-owner",
    ) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(document_ids))
        if not unique_ids:
            raise StoreValidationError("document_ids is required")
        with self._transaction() as conn:
            target = self._require_node(conn, target_node_id)
            if target["status"] != "active" or target["kind"] == "smart":
                raise StoreValidationError("documents can only be placed in an active physical node")
            moved = []
            for document_id in unique_ids:
                document = self._require_document(conn, document_id)
                if document["library_id"] != target["library_id"]:
                    raise StoreValidationError("cross-library move requires reindex migration")
                current = conn.execute(
                    """SELECT node_id FROM document_placements
                       WHERE document_id = ? AND placement_type = 'PRIMARY'""",
                    (document_id,),
                ).fetchone()
                if current and current["node_id"] == target_node_id:
                    continue
                conn.execute(
                    "DELETE FROM document_placements WHERE document_id = ? AND placement_type = 'PRIMARY'",
                    (document_id,),
                )
                conn.execute(
                    """INSERT INTO document_placements(document_id, node_id, placement_type, created_at)
                       VALUES (?, ?, 'PRIMARY', ?)""",
                    (document_id, target_node_id, utc_now()),
                )
                status = "unclassified" if target["is_unclassified"] else "active"
                conn.execute(
                    "UPDATE documents SET status = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                    (status, utc_now(), document_id),
                )
                moved.append({
                    "document_id": document_id,
                    "from_node_id": current["node_id"] if current else None,
                    "to_node_id": target_node_id,
                })
            library = self._require_library(conn, target["library_id"])
            change_id = self._record_change(
                conn, target["library_id"], library["taxonomy_version"], library["taxonomy_version"],
                actor, f"移动 {len(moved)} 个文档",
                {"op": "MOVE_DOCUMENTS", "moves": moved},
                {"op": "MOVE_DOCUMENTS", "moves": [
                    {"document_id": item["document_id"], "to_node_id": item["from_node_id"]}
                    for item in moved
                ]},
                "document_batch", target_node_id,
                after={"moved": len(moved), "target_node_id": target_node_id},
            )
            return {"moved_count": len(moved), "change_set_id": change_id}

    def add_alias(self, document_id: str, node_id: str, actor: str = "local-owner") -> dict[str, Any]:
        with self._transaction() as conn:
            document = self._require_document(conn, document_id)
            node = self._require_node(conn, node_id)
            if document["library_id"] != node["library_id"] or node["status"] != "active":
                raise StoreValidationError("alias node must belong to the document library")
            primary = conn.execute(
                "SELECT node_id FROM document_placements WHERE document_id = ? AND placement_type = 'PRIMARY'",
                (document_id,),
            ).fetchone()
            if primary and primary["node_id"] == node_id:
                raise StoreConflict("primary placement cannot also be an alias")
            conn.execute(
                """INSERT OR IGNORE INTO document_placements(document_id, node_id, placement_type, created_at)
                   VALUES (?, ?, 'ALIAS', ?)""",
                (document_id, node_id, utc_now()),
            )
            library = self._require_library(conn, document["library_id"])
            self._record_change(
                conn, document["library_id"], library["taxonomy_version"], library["taxonomy_version"],
                actor, f"添加文档别名 {document['title']}",
                {"op": "ADD_ALIAS", "document_id": document_id, "node_id": node_id},
                {"op": "REMOVE_ALIAS", "document_id": document_id, "node_id": node_id},
                "document", document_id, after={"alias_node_id": node_id},
            )
        return self.get_document(document_id)

    def remove_alias(self, document_id: str, node_id: str, actor: str = "local-owner") -> dict[str, Any]:
        with self._transaction() as conn:
            document = self._require_document(conn, document_id)
            result = conn.execute(
                """DELETE FROM document_placements
                   WHERE document_id = ? AND node_id = ? AND placement_type = 'ALIAS'""",
                (document_id, node_id),
            )
            if result.rowcount == 0:
                raise StoreNotFound("document alias not found")
            library = self._require_library(conn, document["library_id"])
            self._record_change(
                conn, document["library_id"], library["taxonomy_version"], library["taxonomy_version"],
                actor, f"删除文档别名 {document['title']}",
                {"op": "REMOVE_ALIAS", "document_id": document_id, "node_id": node_id},
                {"op": "ADD_ALIAS", "document_id": document_id, "node_id": node_id},
                "document", document_id, before={"alias_node_id": node_id},
            )
        return self.get_document(document_id)

    def list_tags(self, library_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            self._require_library(conn, library_id)
            return [dict(row) for row in conn.execute(
                """SELECT t.*,
                   (SELECT COUNT(*) FROM document_tags dt WHERE dt.tag_id = t.id) AS document_count
                   FROM tags t WHERE t.library_id = ? ORDER BY lower(t.name)""",
                (library_id,),
            ).fetchall()]
        finally:
            conn.close()

    def create_tag(self, library_id: str, name: str, color: str = "") -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise StoreValidationError("tag name is required")
        tag_id = new_id("tag")
        with self._transaction() as conn:
            self._require_library(conn, library_id)
            try:
                conn.execute(
                    "INSERT INTO tags(id, library_id, name, color, created_at) VALUES (?, ?, ?, ?, ?)",
                    (tag_id, library_id, name, color.strip(), utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(f"tag '{name}' already exists") from exc
        return {"id": tag_id, "library_id": library_id, "name": name, "color": color.strip()}

    def set_document_tags(self, document_id: str, tag_ids: list[str]) -> dict[str, Any]:
        tag_ids = list(dict.fromkeys(tag_ids))
        with self._transaction() as conn:
            document = self._require_document(conn, document_id)
            for tag_id in tag_ids:
                tag = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
                if tag is None or tag["library_id"] != document["library_id"]:
                    raise StoreValidationError(f"tag '{tag_id}' does not belong to document library")
            conn.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
            for tag_id in tag_ids:
                conn.execute(
                    """INSERT INTO document_tags(document_id, tag_id, source, confidence, created_at)
                       VALUES (?, ?, 'manual', NULL, ?)""",
                    (document_id, tag_id, utc_now()),
                )
        return self.get_document(document_id)

    def queue_ingest(
        self,
        library_id: str,
        target_node_id: str,
        source_path: str,
        idempotency_key: str,
        document_id: Optional[str] = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._transaction() as conn:
            self._require_library(conn, library_id)
            target = self._require_node(conn, target_node_id)
            if target["library_id"] != library_id or target["status"] != "active":
                raise StoreValidationError("target node does not belong to active library")
            existing = conn.execute(
                "SELECT * FROM ingest_jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                return dict(existing)

            # Create or find document
            if document_id:
                doc = conn.execute(
                    "SELECT * FROM documents WHERE id = ? AND library_id = ?",
                    (document_id, library_id),
                ).fetchone()
                if doc is None:
                    raise StoreNotFound(f"document '{document_id}' not found in library '{library_id}'")
            else:
                # Auto-create document from source_path
                source_name = source_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                doc_id = new_id("doc")
                conn.execute(
                    """INSERT INTO documents
                       (id, library_id, title, mime_type, source_path, source_name,
                        status, index_status, owner, metadata_json, revision,
                        created_at, updated_at)
                       VALUES (?, ?, ?, 'text/plain', ?, ?, 'unclassified', 'pending',
                               'local-owner', '{}', 1, ?, ?)""",
                    (doc_id, library_id, source_name, source_path, source_name, now, now),
                )
                document_id = doc_id

            # Create a new version for this ingest
            version_id = new_id("ver")
            max_ver = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) FROM document_versions WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO document_versions
                   (id, document_id, version_number, content_hash, source_uri,
                    size_bytes, parser_version, index_status, created_at)
                   VALUES (?, ?, ?, '', ?, 0, 'v2.1', 'pending', ?)""",
                (version_id, document_id, max_ver + 1, source_path, now),
            )

            # Create job linked to document and version
            job_id = new_id("job")
            conn.execute(
                """INSERT INTO ingest_jobs
                   (id, library_id, target_node_id, source_path, document_id, version_id,
                    state, progress, error, retry_count, idempotency_key, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, '', 0, ?, ?, ?)""",
                (
                    job_id, library_id, target_node_id, source_path, document_id,
                    version_id, idempotency_key, now, now,
                ),
            )
            # Update document index_status to pending
            conn.execute(
                "UPDATE documents SET index_status = 'pending', updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            return dict(conn.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone())

    def list_jobs(self, library_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            limit = min(max(int(limit), 1), 200)
            if library_id:
                self._require_library(conn, library_id)
                rows = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE library_id = ? ORDER BY created_at DESC LIMIT ?",
                    (library_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ingest_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_audit_events(self, library_id: str, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            self._require_library(conn, library_id)
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE library_id = ? ORDER BY created_at DESC LIMIT ?",
                (library_id, min(max(int(limit), 1), 200)),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def stats(self) -> dict[str, int]:
        conn = self._connect()
        try:
            return {
                "schema_version": SCHEMA_VERSION,
                "libraries": conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0],
                "nodes": conn.execute("SELECT COUNT(*) FROM taxonomy_nodes").fetchone()[0],
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "queued_jobs": conn.execute(
                    "SELECT COUNT(*) FROM ingest_jobs WHERE state IN ('queued', 'running')"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Worker lease methods
    # ------------------------------------------------------------------

    def release_expired_leases(self) -> int:
        """Reclaim jobs whose lease has expired back to queued state."""
        now = utc_now()
        with self._transaction() as conn:
            result = conn.execute(
                """UPDATE ingest_jobs SET state = 'queued', worker_id = '',
                   lease_until = '', updated_at = ?
                   WHERE state = 'running' AND lease_until != '' AND lease_until < ?""",
                (now, now),
            )
            return result.rowcount

    def claim_next_job(
        self, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> Optional[dict[str, Any]]:
        """Atomically claim the next queued job for processing."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        now_str = now.isoformat(timespec="seconds")

        with self._transaction() as conn:
            row = conn.execute(
                """SELECT id FROM ingest_jobs
                   WHERE state = 'queued' AND retry_count < max_retries
                   ORDER BY created_at LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """UPDATE ingest_jobs SET state = 'running', worker_id = ?,
                   lease_until = ?, updated_at = ? WHERE id = ?""",
                (worker_id, lease_until, now_str, row["id"]),
            )
            return dict(conn.execute(
                "SELECT * FROM ingest_jobs WHERE id = ?", (row["id"],)
            ).fetchone())

    def complete_job(
        self, job_id: str, chunks_indexed: int = 0
    ) -> dict[str, Any]:
        """Mark a job as successfully completed."""
        now = utc_now()
        with self._transaction() as conn:
            conn.execute(
                """UPDATE ingest_jobs SET state = 'completed', progress = 100,
                   chunks_indexed = ?, worker_id = '', lease_until = '',
                   updated_at = ? WHERE id = ?""",
                (chunks_indexed, now, job_id),
            )
            job = conn.execute(
                "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job and job["document_id"]:
                conn.execute(
                    """UPDATE documents SET index_status = 'ready',
                       revision = revision + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, job["document_id"]),
                )
            return dict(job) if job else {}

    def fail_job(self, job_id: str, error_message: str) -> dict[str, Any]:
        """Mark a job as failed; re-queue if retries remain."""
        now = utc_now()
        with self._transaction() as conn:
            job = conn.execute(
                "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise StoreNotFound(f"job '{job_id}' not found")
            new_retry = job["retry_count"] + 1
            if new_retry >= job["max_retries"]:
                new_state = "failed"
            else:
                new_state = "queued"
            conn.execute(
                """UPDATE ingest_jobs SET state = ?, error = ?,
                   retry_count = ?, worker_id = '', lease_until = '',
                   updated_at = ? WHERE id = ?""",
                (new_state, error_message[:2000], new_retry, now, job_id),
            )
            if job["document_id"]:
                idx_status = "failed" if new_state == "failed" else "pending"
                conn.execute(
                    """UPDATE documents SET index_status = ?,
                       revision = revision + 1, updated_at = ?
                       WHERE id = ?""",
                    (idx_status, now, job["document_id"]),
                )
            return dict(conn.execute(
                "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)
            ).fetchone())

    def renew_lease(
        self, job_id: str, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> bool:
        """Extend the lease for a running job (heartbeat)."""
        from datetime import timedelta
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat(timespec="seconds")
        with self._transaction() as conn:
            result = conn.execute(
                """UPDATE ingest_jobs SET lease_until = ?, updated_at = ?
                   WHERE id = ? AND state = 'running' AND worker_id = ?""",
                (lease_until, utc_now(), job_id, worker_id),
            )
            return result.rowcount > 0

    # ------------------------------------------------------------------
    # Document Version management
    # ------------------------------------------------------------------

    def create_version(
        self,
        document_id: str,
        content_hash: str,
        source_uri: str,
        size_bytes: int,
        parser_version: str = "v2.1",
    ) -> dict[str, Any]:
        """Create a new document version. Returns the new version record."""
        now = utc_now()
        version_id = f"ver-{uuid.uuid4().hex}"
        with self._transaction() as conn:
            doc = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if doc is None:
                raise StoreNotFound(f"document '{document_id}' not found")
            max_ver = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) FROM document_versions WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO document_versions
                   (id, document_id, version_number, content_hash, source_uri,
                    size_bytes, parser_version, index_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (version_id, document_id, max_ver + 1, content_hash, source_uri,
                 size_bytes, parser_version, now),
            )
            conn.execute(
                "UPDATE documents SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            return dict(conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone())

    def complete_version(
        self, version_id: str, chunk_count: int, weaviate_collection: str
    ) -> dict[str, Any]:
        """Mark a version as successfully indexed."""
        now = utc_now()
        with self._transaction() as conn:
            conn.execute(
                """UPDATE document_versions
                   SET index_status = 'ready', chunk_count = ?,
                       weaviate_collection = ?
                   WHERE id = ?""",
                (chunk_count, weaviate_collection, version_id),
            )
            return dict(conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone())

    def fail_version(self, version_id: str, error_message: str = "") -> dict[str, Any]:
        """Mark a version as failed."""
        now = utc_now()
        with self._transaction() as conn:
            conn.execute(
                "UPDATE document_versions SET index_status = 'failed' WHERE id = ?",
                (version_id,),
            )
            return dict(conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone())

    def activate_version(self, version_id: str) -> dict[str, Any]:
        """Atomically set a version as the current active version for its document.

        This is the 'index revision switch' - after this call, retrieval APIs
        will return chunks from this version.
        """
        now = utc_now()
        with self._transaction() as conn:
            ver = conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone()
            if ver is None:
                raise StoreNotFound(f"version '{version_id}' not found")
            if ver["index_status"] != "ready":
                raise StoreError(
                    f"version '{version_id}' is not ready (status={ver['index_status']})"
                )
            conn.execute(
                """UPDATE documents SET current_version_id = ?,
                   index_status = 'ready', revision = revision + 1, updated_at = ?
                   WHERE id = ?""",
                (version_id, now, ver["document_id"]),
            )
            return dict(conn.execute(
                "SELECT * FROM documents WHERE id = ?", (ver["document_id"],)
            ).fetchone())

    def rollback_version(self, document_id: str, target_version_id: str) -> dict[str, Any]:
        """Rollback a document to a previous version.

        The target version must be in 'ready' state.
        """
        now = utc_now()
        with self._transaction() as conn:
            target = conn.execute(
                "SELECT * FROM document_versions WHERE id = ? AND document_id = ?",
                (target_version_id, document_id),
            ).fetchone()
            if target is None:
                raise StoreNotFound(
                    f"version '{target_version_id}' not found for document '{document_id}'"
                )
            if target["index_status"] != "ready":
                raise StoreError(
                    f"target version '{target_version_id}' is not ready "
                    f"(status={target['index_status']})"
                )
            conn.execute(
                """UPDATE documents SET current_version_id = ?,
                   revision = revision + 1, updated_at = ?
                   WHERE id = ?""",
                (target_version_id, now, document_id),
            )
            return dict(conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone())

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        """List all versions for a document, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM document_versions WHERE document_id = ?
                   ORDER BY version_number DESC""",
                (document_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_active_version(self, document_id: str) -> Optional[dict[str, Any]]:
        """Get the currently active version for a document."""
        conn = self._connect()
        try:
            doc = conn.execute(
                "SELECT current_version_id FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if doc is None or not doc["current_version_id"]:
                return None
            row = conn.execute(
                "SELECT * FROM document_versions WHERE id = ?",
                (doc["current_version_id"],),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Classification Proposals
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        library_id: str,
        llm_model: str = "",
        llm_response: dict | None = None,
        routing_cards: list | None = None,
        subtree: list | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        created_by: str = "auto-classifier",
    ) -> dict[str, Any]:
        """Create a new classification proposal."""
        now = utc_now()
        proposal_id = f"prop-{uuid.uuid4().hex}"
        with self._transaction() as conn:
            self._require_library(conn, library_id)
            conn.execute(
                """INSERT INTO classification_proposals
                   (id, library_id, status, llm_model, llm_response_json,
                    routing_cards_json, subtree_json, prompt_tokens, completion_tokens,
                    created_by, created_at, updated_at)
                   VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id, library_id, llm_model,
                    json.dumps(llm_response or {}),
                    json.dumps(routing_cards or []),
                    json.dumps(subtree or []),
                    prompt_tokens, completion_tokens,
                    created_by, now, now,
                ),
            )
            return dict(conn.execute(
                "SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)
            ).fetchone())

    def add_proposal_item(
        self,
        proposal_id: str,
        document_id: str,
        source_node_id: str,
        target_node_id: str,
        confidence: float = 0.0,
        reason_code: str = "",
        llm_reasoning: str = "",
    ) -> dict[str, Any]:
        """Add a classification item to a proposal with schema validation.

        Validates:
        - source_node_id and target_node_id exist in the same library
        - target_node_id is not the unclassified node
        - document exists and belongs to the same library
        """
        now = utc_now()
        item_id = f"pi-{uuid.uuid4().hex}"
        with self._transaction() as conn:
            proposal = conn.execute(
                "SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise StoreNotFound(f"proposal '{proposal_id}' not found")
            if proposal["status"] != "draft":
                raise StoreValidationError(
                    f"proposal '{proposal_id}' is not in draft status (current: {proposal['status']})"
                )

            library_id = proposal["library_id"]

            # Validate source node
            source_node = conn.execute(
                "SELECT * FROM taxonomy_nodes WHERE id = ? AND library_id = ?",
                (source_node_id, library_id),
            ).fetchone()
            if source_node is None:
                raise StoreValidationError(
                    f"source node '{source_node_id}' not found in library '{library_id}'"
                )

            # Validate target node
            target_node = conn.execute(
                "SELECT * FROM taxonomy_nodes WHERE id = ? AND library_id = ?",
                (target_node_id, library_id),
            ).fetchone()
            if target_node is None:
                raise StoreValidationError(
                    f"target node '{target_node_id}' not found in library '{library_id}'"
                )
            if target_node["is_unclassified"]:
                raise StoreValidationError(
                    f"target node '{target_node_id}' is the unclassified node"
                )

            # Validate document
            doc = conn.execute(
                "SELECT * FROM documents WHERE id = ? AND library_id = ?",
                (document_id, library_id),
            ).fetchone()
            if doc is None:
                raise StoreNotFound(
                    f"document '{document_id}' not found in library '{library_id}'"
                )

            # Get current version_id for lock
            version_id = doc["current_version_id"] or ""

            # Get current primary placement
            placement = conn.execute(
                """SELECT node_id FROM document_placements
                   WHERE document_id = ? AND placement_type = 'PRIMARY'""",
                (document_id,),
            ).fetchone()
            previous_node_id = placement["node_id"] if placement else source_node_id

            conn.execute(
                """INSERT INTO proposal_items
                   (id, proposal_id, document_id, version_id, source_node_id,
                    target_node_id, status, confidence, reason_code, llm_reasoning,
                    previous_node_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
                (
                    item_id, proposal_id, document_id, version_id,
                    source_node_id, target_node_id, confidence,
                    reason_code, llm_reasoning, previous_node_id, now, now,
                ),
            )
            return dict(conn.execute(
                "SELECT * FROM proposal_items WHERE id = ?", (item_id,)
            ).fetchone())

    def list_proposals(
        self, library_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List classification proposals."""
        conn = self._connect()
        try:
            query = "SELECT * FROM classification_proposals WHERE 1=1"
            params = []
            if library_id:
                query += " AND library_id = ?"
                params.append(library_id)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(min(max(int(limit), 1), 200))
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Get a proposal with its items."""
        conn = self._connect()
        try:
            proposal = conn.execute(
                "SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise StoreNotFound(f"proposal '{proposal_id}' not found")
            items = conn.execute(
                """SELECT * FROM proposal_items WHERE proposal_id = ?
                   ORDER BY created_at""",
                (proposal_id,),
            ).fetchall()
            result = dict(proposal)
            result["items"] = [dict(i) for i in items]
            return result
        finally:
            conn.close()

    def approve_proposal_item(self, item_id: str) -> dict[str, Any]:
        """Mark a proposal item as approved (ready to apply)."""
        now = utc_now()
        with self._transaction() as conn:
            item = conn.execute(
                "SELECT * FROM proposal_items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None:
                raise StoreNotFound(f"proposal item '{item_id}' not found")
            if item["status"] != "pending":
                raise StoreValidationError(
                    f"item '{item_id}' is not pending (current: {item['status']})"
                )
            conn.execute(
                "UPDATE proposal_items SET status = 'approved', updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            return dict(conn.execute(
                "SELECT * FROM proposal_items WHERE id = ?", (item_id,)
            ).fetchone())

    def reject_proposal_item(self, item_id: str, reason: str = "") -> dict[str, Any]:
        """Mark a proposal item as rejected."""
        now = utc_now()
        with self._transaction() as conn:
            item = conn.execute(
                "SELECT * FROM proposal_items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None:
                raise StoreNotFound(f"proposal item '{item_id}' not found")
            if item["status"] != "pending":
                raise StoreValidationError(
                    f"item '{item_id}' is not pending (current: {item['status']})"
                )
            conn.execute(
                """UPDATE proposal_items SET status = 'rejected',
                   llm_reasoning = CASE WHEN ? != '' THEN ? ELSE llm_reasoning END,
                   updated_at = ? WHERE id = ?""",
                (reason, reason, now, item_id),
            )
            return dict(conn.execute(
                "SELECT * FROM proposal_items WHERE id = ?", (item_id,)
            ).fetchone())

    def apply_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Apply all approved items in a proposal.

        For each approved item:
        - Update document's primary placement to target_node_id
        - Record the change for potential revert
        """
        now = utc_now()
        with self._transaction() as conn:
            proposal = conn.execute(
                "SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise StoreNotFound(f"proposal '{proposal_id}' not found")

            items = conn.execute(
                """SELECT * FROM proposal_items WHERE proposal_id = ? AND status = 'approved'""",
                (proposal_id,),
            ).fetchall()

            applied_count = 0
            for item in items:
                # Update primary placement
                conn.execute(
                    """UPDATE document_placements SET node_id = ?
                       WHERE document_id = ? AND placement_type = 'PRIMARY'""",
                    (item["target_node_id"], item["document_id"]),
                )
                # If no placement exists, create one
                existing = conn.execute(
                    """SELECT 1 FROM document_placements
                       WHERE document_id = ? AND placement_type = 'PRIMARY'""",
                    (item["document_id"],),
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO document_placements
                           (document_id, node_id, placement_type, created_at)
                           VALUES (?, ?, 'PRIMARY', ?)""",
                        (item["document_id"], item["target_node_id"], now),
                    )

                # Update document status
                conn.execute(
                    """UPDATE documents SET status = 'classified',
                       revision = revision + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, item["document_id"]),
                )

                # Mark item as applied
                conn.execute(
                    """UPDATE proposal_items SET status = 'applied', applied_at = ?,
                       updated_at = ? WHERE id = ?""",
                    (now, now, item["id"]),
                )
                applied_count += 1

            # Update proposal status
            conn.execute(
                """UPDATE classification_proposals SET status = 'applied', updated_at = ?
                   WHERE id = ?""",
                (now, proposal_id),
            )

            return {
                "proposal_id": proposal_id,
                "status": "applied",
                "applied_count": applied_count,
            }

    def revert_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Revert all applied items in a proposal to their previous nodes."""
        now = utc_now()
        with self._transaction() as conn:
            proposal = conn.execute(
                "SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise StoreNotFound(f"proposal '{proposal_id}' not found")

            items = conn.execute(
                """SELECT * FROM proposal_items WHERE proposal_id = ? AND status = 'applied'""",
                (proposal_id,),
            ).fetchall()

            reverted_count = 0
            for item in items:
                if not item["previous_node_id"]:
                    continue

                # Restore primary placement
                conn.execute(
                    """UPDATE document_placements SET node_id = ?
                       WHERE document_id = ? AND placement_type = 'PRIMARY'""",
                    (item["previous_node_id"], item["document_id"]),
                )

                # Update document status
                conn.execute(
                    """UPDATE documents SET status = 'unclassified',
                       revision = revision + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, item["document_id"]),
                )

                # Mark item as reverted
                conn.execute(
                    """UPDATE proposal_items SET status = 'reverted', reverted_at = ?,
                       updated_at = ? WHERE id = ?""",
                    (now, now, item["id"]),
                )
                reverted_count += 1

            # Update proposal status
            conn.execute(
                """UPDATE classification_proposals SET status = 'reverted', updated_at = ?
                   WHERE id = ?""",
                (now, proposal_id),
            )

            return {
                "proposal_id": proposal_id,
                "status": "reverted",
                "reverted_count": reverted_count,
            }
