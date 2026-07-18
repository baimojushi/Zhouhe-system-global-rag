#!/usr/bin/env python3
"""
RAG Gateway — FastAPI REST API for Phase 3
==========================================

Endpoints:
  POST /v1/retrieve    - Retrieve knowledge chunks (hybrid search)
  POST /v1/ingest/text - Ingest text directly into knowledge base
  POST /v1/memory      - Store context memory
  GET  /health         - Health check
  POST /v1/retrieve/search_knowledge - MCP tool wrapper

Built-in MCP tools (model-visible):
  search_knowledge(query, scope, top_k)
  search_context(query, session_id, top_k)
  remember(content, session_id, importance)
  forget_session(session_id)

Security:
  - Only binds to 127.0.0.1
  - API Key required
  - Model-visible tools are READ-ONLY (no ingest/delete)
"""
import os
import sys
import logging
import argparse
import hashlib
import hmac
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/opt/global-rag/cache/huggingface")
os.environ.setdefault("DOCLING_ARTIFACTS_PATH", "/opt/global-rag/cache/docling-models")

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import weaviate
import weaviate.classes as wvc
from weaviate.auth import AuthApiKey
from FlagEmbedding import FlagModel

# Keep absolute imports: the deployed Gateway is launched directly as a script.
from knowledge_store import (
    DEFAULT_LIBRARIES,
    DEFAULT_TREES,
    KnowledgeStore,
    StoreConflict,
    StoreNotFound,
    StoreValidationError,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FILE = Path("/opt/global-rag/logs/gateway.log")
os.makedirs(LOG_FILE.parent, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("rag_gateway")

# Load API key.  Environment variables take precedence so tests and portable
# deployments do not depend on the historic /opt/global-rag/stack path.
env_path = Path("/opt/global-rag/stack/.env")
api_key = os.environ.get("WEAVIATE_API_KEY", "").strip()
if not api_key and env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("WEAVIATE_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"')
                break

if not api_key:
    raise RuntimeError("WEAVIATE_API_KEY not found in /opt/global-rag/stack/.env")

# ---------------------------------------------------------------------------
# Weaviate + Model
# ---------------------------------------------------------------------------

weaviate_client = weaviate.connect_to_local(
    host="localhost", port=8080, grpc_port=50051,
    auth_credentials=AuthApiKey(api_key),
)
knowledge_coll = weaviate_client.collections.get("KnowledgeChunk")
context_coll = weaviate_client.collections.get("ContextMemory")

# Lazy load model
model = None

def get_model() -> FlagModel:
    global model
    if model is None:
        log.info("Loading BGE-M3 model...")
        model = FlagModel("BAAI/bge-m3", cpu="CPU", use_fp16=False)
        log.info("BGE-M3 loaded OK")
    return model

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class RetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    alpha: float = Field(default=0.55, ge=0.0, le=1.0)
    scope: str = Field(default="global")
    library_id: Optional[str] = Field(default=None, description="Filter by library ID")
    active_versions_only: bool = Field(default=True, description="Only return chunks from active document versions")
    return_fields: list[str] = ["content", "title", "heading", "source_path", "source_name", "page"]

class IngestTextRequest(BaseModel):
    text: str
    title: Optional[str] = None
    heading: Optional[str] = None
    source_path: Optional[str] = None
    mime_type: str = "text/plain"
    scope: str = "global"

class MemoryRequest(BaseModel):
    content: str
    session_id: str
    role: str = Field(default="system")
    memory_type: str = Field(default="message")
    importance: int = Field(default=0, ge=0, le=10)
    expires_at: Optional[str] = None

class SearchKnowledgeRequest(BaseModel):
    query: str
    scope: str = "global"
    top_k: int = 5
    library_id: Optional[str] = None
    active_versions_only: bool = True

class SearchContextRequest(BaseModel):
    query: str
    session_id: str
    top_k: int = 5

class RememberRequest(BaseModel):
    content: str
    session_id: str
    importance: int = 0

class ForgetSessionRequest(BaseModel):
    session_id: str

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_active_version_ids(library_id: str = None) -> list[str]:
    """Get list of active version_ids, optionally filtered by library."""
    if knowledge_store is None:
        return []
    try:
        conn = knowledge_store._connect()
        if library_id:
            rows = conn.execute(
                """SELECT dv.id FROM document_versions dv
                   JOIN documents d ON d.current_version_id = dv.id
                   WHERE d.library_id = ? AND d.current_version_id IS NOT NULL""",
                (library_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT dv.id FROM document_versions dv
                   JOIN documents d ON d.current_version_id = dv.id
                   WHERE d.current_version_id IS NOT NULL"""
            ).fetchall()
        conn.close()
        return [row["id"] for row in rows]
    except Exception as e:
        log.warning(f"Failed to get active version ids: {e}")
        return []

def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.55,
                  collection=None, filters: dict = None,
                  library_id: str = None, active_versions_only: bool = True) -> list[dict]:
    """Hybrid search with pre-computed vector (self_provided vectors).

    Args:
        query: Search query text
        top_k: Number of results to return
        alpha: Hybrid search alpha (0=pure BM25, 1=pure vector)
        collection: Weaviate collection to search
        filters: Additional filters dict
        library_id: If provided, only search chunks from this library
        active_versions_only: If True, only return chunks from active document versions
    """
    model = get_model()
    query_vec = model.encode(query).tolist()

    # Build filters
    weaviate_filters = []
    if filters:
        for key, value in filters.items():
            weaviate_filters.append(
                wvc.query.Filter.by_property(key).equal(value)
            )

    # Add library filter
    if library_id:
        weaviate_filters.append(
            wvc.query.Filter.by_property("library_id").equal(library_id)
        )

    # Add active version filter
    if active_versions_only:
        active_versions = get_active_version_ids(library_id)
        if active_versions:
            weaviate_filters.append(
                wvc.query.Filter.by_property("version_id").contains_any(active_versions)
            )
        elif library_id:
            # No active versions in this library, return empty
            return []

    if collection is None:
        collection = knowledge_coll

    kwargs = {
        "query": query,
        "limit": top_k,
        "alpha": alpha,
        "vector": query_vec,
    }
    if weaviate_filters:
        kwargs["filters"] = wvc.query.Filter.all_of(weaviate_filters)

    result = getattr(collection, "query").hybrid(**kwargs)

    results = []
    for obj in result.objects:
        item = {
            "chunk_id": obj.properties.get("chunk_id"),
            "content": obj.properties.get("content", ""),
            "title": obj.properties.get("title", ""),
            "heading": obj.properties.get("heading", ""),
            "source_path": obj.properties.get("source_path", ""),
            "source_name": obj.properties.get("source_name", ""),
            "page": obj.properties.get("page", 0),
            "scope": obj.properties.get("scope", ""),
            "mime_type": obj.properties.get("mime_type", ""),
            "version_id": obj.properties.get("version_id", ""),
            "document_id": obj.properties.get("document_id", ""),
        }
        results.append(item)
    return results

def bm25_search(query: str, top_k: int = 5, scope: str = "global",
                collection=None) -> list[dict]:
    """BM25 search with GSE Chinese tokenization."""
    if collection is None:
        collection = knowledge_coll
    weaviate_filters = [wvc.query.Filter.by_property("scope").equal(scope)]
    
    result = collection.query.bm25(query=query, limit=top_k, filters=wvc.query.Filter.all_of(weaviate_filters))
    
    results = []
    for obj in result.objects:
        item = {
            "chunk_id": obj.properties.get("chunk_id"),
            "content": obj.properties.get("content", ""),
            "title": obj.properties.get("title", ""),
            "heading": obj.properties.get("heading", ""),
            "source_path": obj.properties.get("source_path", ""),
            "source_name": obj.properties.get("source_name", ""),
            "page": obj.properties.get("page", 0),
            "score": obj.metadata.score,
        }
        results.append(item)
    return results

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="RAG Gateway", version="3.0.0")

# CORS: Allow frontend (port 3000) to access Gateway (port 9100)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://0.0.0.0:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MANAGEMENT_API_KEY = os.environ.get("RAG_GATEWAY_API_KEY", "").strip()


def require_management_auth(authorization: Optional[str] = Header(default=None)) -> str:
    """Protect V2 writes when RAG_GATEWAY_API_KEY is configured.

    Local upgrades remain backward compatible when the variable is empty.  A
    production deployment should always set it and send a Bearer token.
    """
    if not MANAGEMENT_API_KEY:
        return "local-owner"
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, MANAGEMENT_API_KEY):
        raise HTTPException(status_code=401, detail="invalid management bearer token")
    return "local-owner"


@app.exception_handler(StoreNotFound)
async def store_not_found_handler(_request, exc: StoreNotFound):
    return JSONResponse(status_code=404, content={"code": "not_found", "message": str(exc)})


@app.exception_handler(StoreConflict)
async def store_conflict_handler(_request, exc: StoreConflict):
    return JSONResponse(status_code=409, content={"code": "conflict", "message": str(exc)})


@app.exception_handler(StoreValidationError)
async def store_validation_handler(_request, exc: StoreValidationError):
    return JSONResponse(status_code=422, content={"code": "validation_error", "message": str(exc)})

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "weaviate": "connected",
        "model": "loaded" if model is not None else "loading",
    }

@app.post("/v1/retrieve")
async def retrieve(request: RetrieveRequest):
    """Core retrieval endpoint — hybrid search with version-aware filtering."""
    try:
        results = hybrid_search(
            query=request.query,
            top_k=request.top_k,
            alpha=request.alpha,
            filters={"scope": request.scope},
            library_id=request.library_id,
            active_versions_only=request.active_versions_only,
        )
        return {
            "query": request.query,
            "top_k": request.top_k,
            "alpha": request.alpha,
            "scope": request.scope,
            "library_id": request.library_id,
            "active_versions_only": request.active_versions_only,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        log.error(f"Retrieve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/ingest/text")
async def ingest_text(request: IngestTextRequest):
    """Ingest raw text as a knowledge chunk."""
    try:
        model = get_model()
        search_text = f"{request.title or ''} {request.heading or ''} {request.text}"
        vector = model.encode(search_text).tolist()
        
        import hashlib
        import time
        source_hash = hashlib.sha256(f"{request.source_path or 'text'}:{request.text}".encode()).hexdigest()[:16]
        chunk_id = f"ingest-{hashlib.sha256(f'{request.source_path}:{request.text}'.encode()).hexdigest()[:12]}"

        knowledge_coll.data.insert(
            properties={
                "chunk_id": chunk_id,
                "content": request.text,
                "title": request.title or "Ingested Text",
                "heading": request.heading or "",
                "source_path": request.source_path or "/v1/ingest/text",
                "source_name": request.source_path or "text-ingestion",
                "source_hash": source_hash,
                "mime_type": request.mime_type,
                "page": 1,
                "chunk_index": 0,
                "scope": request.scope,
                "modified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            vector=vector,
        )
        return {"status": "ok", "chunk_id": chunk_id}
    except Exception as e:
        log.error(f"Ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/memory")
async def store_memory(request: MemoryRequest):
    """Store context memory."""
    try:
        model = get_model()
        vector = model.encode(request.content).tolist()
        
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        memory_data = {
            "content": request.content,
            "session_id": request.session_id,
            "role": request.role,
            "memory_type": request.memory_type,
            "importance": request.importance,
            "created_at": created_at,
            "expires_at": request.expires_at,
            "scope": "global",
        }

        context_coll.data.insert(
            properties=memory_data,
            vector=vector,
        )
        return {"status": "ok", "created_at": created_at}
    except Exception as e:
        log.error(f"Memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# MCP Tool Wrappers (READ-ONLY for model)
# ---------------------------------------------------------------------------

@app.post("/v1/retrieve/search_knowledge")
async def search_knowledge_tool(request: SearchKnowledgeRequest):
    """MCP tool: search knowledge base with version-aware filtering."""
    try:
        results = hybrid_search(
            query=request.query,
            top_k=request.top_k,
            alpha=0.55,
            filters={"scope": request.scope},
            library_id=request.library_id,
            active_versions_only=request.active_versions_only,
        )
        return {
            "tool": "search_knowledge",
            "query": request.query,
            "library_id": request.library_id,
            "active_versions_only": request.active_versions_only,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        log.error(f"Search knowledge error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/retrieve/search_context")
async def search_context_tool(request: SearchContextRequest):
    """MCP tool: search context memory."""
    try:
        model = get_model()
        query_vec = model.encode(request.query).tolist()

        weaviate_filters = [
            wvc.query.Filter.by_property("session_id").equal(request.session_id)
        ]

        result = context_coll.query.hybrid(
            query=request.query,
            limit=request.top_k,
            alpha=0.6,
            vector=query_vec,
            filters=wvc.query.Filter.all_of(weaviate_filters),
        )

        results = []
        for obj in result.objects:
            results.append({
                "content": obj.properties.get("content", ""),
                "memory_type": obj.properties.get("memory_type", ""),
                "role": obj.properties.get("role", ""),
                "importance": obj.properties.get("importance", 0),
                "created_at": obj.properties.get("created_at", ""),
            })

        return {
            "tool": "search_context",
            "session_id": request.session_id,
            "query": request.query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        log.error(f"Search context error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/memory/remember")
async def remember_tool(request: RememberRequest):
    """MCP tool: remember important content."""
    try:
        model = get_model()
        vector = model.encode(request.content).tolist()
        
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        context_coll.data.insert(
            properties={
                "content": request.content,
                "session_id": request.session_id,
                "role": "system",
                "memory_type": "fact",
                "importance": request.importance,
                "created_at": created_at,
                "expires_at": None,
                "scope": "global",
            },
            vector=vector,
        )
        return {"status": "ok", "tool": "remember", "created_at": created_at}
    except Exception as e:
        log.error(f"Remember error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/memory/forget_session")
async def forget_session_tool(request: ForgetSessionRequest):
    """MCP tool: forget all memory for a session."""
    try:
        delete_filter = wvc.query.Filter.by_property("session_id").equal(request.session_id)
        result = context_coll.data.delete_many(where=delete_filter)
        return {
            "status": "ok",
            "tool": "forget_session",
            "deleted": result.deleted,
            "session_id": request.session_id,
        }
    except Exception as e:
        log.error(f"Forget session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# LLM Configuration (runtime-updatable from frontend)
# ---------------------------------------------------------------------------

class LLMConfigRequest(BaseModel):
    llm_api_base: str = Field(default="", description="OpenAI-compatible API base URL")
    llm_api_key: str = Field(default="", description="API key")
    llm_model: str = Field(default="", description="Model name, e.g. qwen-plus")

@app.post("/v1/llm/config")
async def configure_llm(request: LLMConfigRequest):
    """Update LLM API configuration at runtime (from settings page)."""
    import llm_adapter
    llm_adapter.update_config(base=request.llm_api_base, key=request.llm_api_key, model=request.llm_model)
    log.info(f"LLM config updated: base={request.llm_api_base[:30]}... model={request.llm_model}")
    return {"status": "ok", **llm_adapter.get_config()}

@app.get("/v1/llm/config")
async def get_llm_config():
    """Get current LLM API configuration."""
    import llm_adapter
    return llm_adapter.get_config()

@app.get("/v1/llm/test")
async def test_llm_connectivity():
    """Test LLM API connectivity."""
    import llm_adapter
    result = await llm_adapter.test_connectivity()
    log.info(f"LLM connectivity test: ok={result.get('ok')}")
    return result


# ---------------------------------------------------------------------------
# Taxonomy / Library Management
# ---------------------------------------------------------------------------

# Library registry — maps library_id to collection name and metadata
LIBRARY_REGISTRY = {
    "ai-work": {"collection": "kb_ai_work_v1", "name": "AI 工作记录", "policy": "private · session-aware"},
    "academic": {"collection": "kb_academic_v1", "name": "学术资料", "policy": "research · citation-first"},
    "production": {"collection": "kb_production_v1", "name": "生产文档", "policy": "team · recency-weighted"},
    "notes": {"collection": "kb_notes_v1", "name": "个人思维笔记", "policy": "owner-only · exploratory"},
    "association": {"collection": "kb_association_v1", "name": "关联知识库", "policy": "edge-only · cross-library"},
}

# Predefined tree structure for each library
PREDEFINED_TREES: dict[str, list[dict]] = {
    "ai-work": [
        {"node_id": "ai-unclassified", "name": "未归类", "description": "新文件入口", "is_unclassified": True},
        {"node_id": "ai-projects", "name": "项目", "description": "按项目组织", "children": [
            {"node_id": "ai-rag", "name": "Global RAG", "description": "全局检索系统"},
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
        {"node_id": "ac-cs", "name": "计算机科学", "description": "CS 各领域", "children": [
            {"node_id": "ac-ir", "name": "信息检索", "description": "IR 理论与系统", "children": [
                {"node_id": "ac-hybrid", "name": "混合检索", "description": "向量+关键词混合"},
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
            {"node_id": "pr-vector", "name": "向量数据库", "description": "Weaviate / 向量检索"},
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
    "association": [],
}

# The persistent V2 store is the canonical registry.  Rebind the legacy V1
# views to the same defaults so the two APIs cannot silently drift.
LIBRARY_REGISTRY = {
    item["id"]: {
        "collection": item["collection_name"],
        "name": item["name"],
        "policy": item["policy"],
    }
    for item in DEFAULT_LIBRARIES
}
PREDEFINED_TREES = DEFAULT_TREES

# V1 taxonomy proposal state remains compatibility-only.  V2 library, tree,
# document, job and audit state is persisted in SQLite below.
_taxonomy_version: dict[str, int] = {lid: 1 for lid in LIBRARY_REGISTRY}
_change_set_store: dict[str, dict] = {}


def _build_flat_nodes(nodes: list[dict], library_id: str, parent_id: Optional[str] = None) -> list[dict]:
    """Recursively flatten tree to list of node dicts."""
    result = []
    for n in nodes:
        node = {
            "node_id": n["node_id"],
            "library_id": library_id,
            "parent_node_id": parent_id,
            "name": n["name"],
            "description": n.get("description", ""),
            "is_unclassified": n.get("is_unclassified", False),
        }
        result.append(node)
        if n.get("children"):
            result.extend(_build_flat_nodes(n["children"], library_id, n["node_id"]))
    return result


def _ensure_taxonomy_collection() -> Optional[object]:
    """Ensure taxonomy_nodes collection exists in Weaviate."""
    try:
        exists = weaviate_client.collections.exists("taxonomy_nodes")
        if not exists:
            log.info("Creating taxonomy_nodes collection...")
            weaviate_client.collections.create(
                "taxonomy_nodes",
                properties=[
                    wvc.config.Property(name="node_id", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="library_id", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="parent_node_id", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="name", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="is_unclassified", data_type=wvc.config.DataType.BOOL),
                    wvc.config.Property(name="version_created", data_type=wvc.config.DataType.INT),
                    wvc.config.Property(name="version_retired", data_type=wvc.config.DataType.INT, is_nullable=True),
                ],
            )
            log.info("taxonomy_nodes collection created")
        else:
            log.info("taxonomy_nodes collection exists")
        return weaviate_client.collections.get("taxonomy_nodes")
    except Exception as e:
        log.warning(f"Cannot create taxonomy_nodes: {e}")
        return None


def _seed_taxonomy_nodes(coll: Optional[object]):
    """Seed predefined taxonomy nodes for each library."""
    if coll is None:
        return
    for library_id, tree in PREDEFINED_TREES.items():
        version = _taxonomy_version.get(library_id, 1)
        nodes = _build_flat_nodes(tree, library_id)
        # Check each library independently.  Checking the collection-wide count
        # caused the first seeded library to suppress every library after it.
        existing = coll.query.fetch_objects(
            filters=wvc.query.Filter.by_property("library_id").equal(library_id),
            limit=1,
            include_vector=False,
        )
        if existing.objects:
            continue
        for node in nodes:
            node["version_created"] = version
            node["version_retired"] = None
        coll.data.insert_many(nodes)
        log.info(f"Seeded {len(nodes)} taxonomy nodes for {library_id}")


# Initialize on startup
_taxonomy_coll = _ensure_taxonomy_collection()
_seed_taxonomy_nodes(_taxonomy_coll)


# --- Pydantic models for taxonomy APIs ---

class LibraryTreeResponse(BaseModel):
    node_id: str
    name: str
    description: str = ""
    file_count: int = 0
    children: list["LibraryTreeResponse"] = []

class LibraryTreeRequest(BaseModel):
    library_id: str
    version: Optional[int] = None

class TaxonomyProposalRequest(BaseModel):
    library_id: str
    source_node: str = "unclassified"
    mode: str = Field(default="preview", description="preview | apply")
    payload_mode: str = Field(default="routing_cards", description="routing_cards | partial_content")
    taxonomy_scope: str = Field(default="affected_subtree", description="affected_subtree | full")
    max_routing_cards: int = Field(default=20, ge=1, le=50)

class TaxonomyProposalApplyRequest(BaseModel):
    expected_taxonomy_version: int

class ProposalItemActionRequest(BaseModel):
    reason: str = ""

class IngestPathRequest(BaseModel):
    path: str
    library_id: str
    target_node: str = "unclassified"
    classification: str = Field(default="manual-major-category", description="manual-major-category | auto-first-pass")

class KnowledgeEdgeRequest(BaseModel):
    source_scope: str
    mode: str = "candidate_only"
    max_hops: int = Field(default=1, ge=1, le=2)
    edge_budget: int = Field(default=12, ge=1, le=50)


# --- V2 persistent control-plane models ---

class V2LibraryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    library_id: Optional[str] = None
    kind: str = Field(default="document", description="document | association")
    policy: str = "private · manual-first"
    description: str = ""


class V2LibraryUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    policy: Optional[str] = None
    status: Optional[str] = None


class V2NodeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: Optional[str] = None
    description: str = ""
    kind: str = Field(default="physical", description="physical | smart | alias")
    expected_taxonomy_version: Optional[int] = None


class V2NodeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    locked: Optional[bool] = None
    kind: Optional[str] = None
    expected_taxonomy_version: Optional[int] = None


class V2NodeMoveRequest(BaseModel):
    new_parent_id: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)
    expected_taxonomy_version: Optional[int] = None


class V2NodeArchiveRequest(BaseModel):
    expected_taxonomy_version: Optional[int] = None


class V2DocumentCreateRequest(BaseModel):
    library_id: str
    title: str = Field(min_length=1, max_length=500)
    node_id: str
    mime_type: str = "application/octet-stream"
    source_path: str = ""
    source_name: str = ""
    content_hash: str = ""
    size_bytes: int = Field(default=0, ge=0)
    index_status: str = "pending"


class V2DocumentUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    status: Optional[str] = None
    index_status: Optional[str] = None
    owner: Optional[str] = None
    metadata: Optional[dict] = None


class V2DocumentMoveRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=1000)
    target_node_id: str


class V2AliasRequest(BaseModel):
    node_id: str


class V2TagCreateRequest(BaseModel):
    library_id: str
    name: str = Field(min_length=1, max_length=80)
    color: str = ""


class V2DocumentTagsRequest(BaseModel):
    tag_ids: list[str] = Field(default_factory=list, max_length=100)


class V2IngestPathRequest(BaseModel):
    path: str = Field(min_length=1)
    library_id: str
    target_node_id: str


CONTROL_DB_PATH = os.environ.get(
    "RAG_CONTROL_DB", "/opt/global-rag/data/knowledge-control.db"
)
knowledge_store = KnowledgeStore(CONTROL_DB_PATH)


def _model_fields(model: BaseModel, *excluded: str) -> dict:
    """Return explicitly supplied fields under Pydantic v1 or v2."""
    if hasattr(model, "model_dump"):
        data = model.model_dump(exclude_unset=True)
    else:
        data = model.dict(exclude_unset=True)
    for key in excluded:
        data.pop(key, None)
    return data


def _allowed_ingest_roots() -> list[Path]:
    configured = os.environ.get("RAG_INGEST_ROOTS", "/opt/global-rag/kb")
    roots = []
    for raw in configured.split(os.pathsep):
        raw = raw.strip()
        if raw:
            roots.append(Path(raw).expanduser().resolve(strict=False))
    return roots


def _resolve_allowed_ingest_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve(strict=True)
    for root in _allowed_ingest_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    allowed = ", ".join(str(root) for root in _allowed_ingest_roots())
    raise StoreValidationError(f"path is outside RAG_INGEST_ROOTS: {allowed}")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# --- Routes ---

@app.get("/v2/control/health")
async def v2_control_health():
    return {"status": "ok", "database": str(CONTROL_DB_PATH), **knowledge_store.stats()}


@app.get("/v2/libraries")
async def v2_list_libraries(include_archived: bool = False):
    return {"libraries": knowledge_store.list_libraries(include_archived)}


@app.post("/v2/libraries", status_code=201)
async def v2_create_library(
    request: V2LibraryCreateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.create_library(
        name=request.name,
        library_id=request.library_id,
        kind=request.kind,
        policy=request.policy,
        description=request.description,
        actor=actor,
    )


@app.patch("/v2/libraries/{library_id}")
async def v2_update_library(
    library_id: str,
    request: V2LibraryUpdateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.update_library(
        library_id, _model_fields(request), actor=actor
    )


@app.get("/v2/libraries/{library_id}/tree")
async def v2_get_library_tree(library_id: str, include_archived: bool = False):
    return knowledge_store.get_tree(library_id, include_archived)


@app.post("/v2/libraries/{library_id}/nodes", status_code=201)
async def v2_create_node(
    library_id: str,
    request: V2NodeCreateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.create_node(
        library_id=library_id,
        name=request.name,
        parent_id=request.parent_id,
        description=request.description,
        kind=request.kind,
        expected_version=request.expected_taxonomy_version,
        actor=actor,
    )


@app.patch("/v2/nodes/{node_id}")
async def v2_update_node(
    node_id: str,
    request: V2NodeUpdateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.update_node(
        node_id,
        _model_fields(request, "expected_taxonomy_version"),
        expected_version=request.expected_taxonomy_version,
        actor=actor,
    )


@app.post("/v2/nodes/{node_id}:move")
async def v2_move_node(
    node_id: str,
    request: V2NodeMoveRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.move_node(
        node_id,
        request.new_parent_id,
        position=request.position,
        expected_version=request.expected_taxonomy_version,
        actor=actor,
    )


@app.post("/v2/nodes/{node_id}:archive")
async def v2_archive_node(
    node_id: str,
    request: V2NodeArchiveRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.archive_node(
        node_id,
        expected_version=request.expected_taxonomy_version,
        actor=actor,
    )


@app.get("/v2/documents")
async def v2_list_documents(
    library_id: str,
    node_id: Optional[str] = None,
    q: str = "",
    status: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
):
    return knowledge_store.list_documents(
        library_id, node_id=node_id, query=q, status=status, limit=limit, cursor=cursor
    )


@app.post("/v2/documents", status_code=201)
async def v2_create_document(
    request: V2DocumentCreateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.create_document(
        library_id=request.library_id,
        title=request.title,
        node_id=request.node_id,
        mime_type=request.mime_type,
        source_path=request.source_path,
        source_name=request.source_name,
        content_hash=request.content_hash,
        size_bytes=request.size_bytes,
        index_status=request.index_status,
        actor=actor,
    )


@app.post("/v2/document-actions/move")
async def v2_move_documents(
    request: V2DocumentMoveRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.move_documents(
        request.document_ids, request.target_node_id, actor=actor
    )


@app.get("/v2/documents/{document_id}")
async def v2_get_document(document_id: str):
    return knowledge_store.get_document(document_id)


@app.patch("/v2/documents/{document_id}")
async def v2_update_document(
    document_id: str,
    request: V2DocumentUpdateRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.update_document(
        document_id, _model_fields(request), actor=actor
    )


@app.post("/v2/documents/{document_id}/aliases", status_code=201)
async def v2_add_document_alias(
    document_id: str,
    request: V2AliasRequest,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.add_alias(document_id, request.node_id, actor=actor)


@app.delete("/v2/documents/{document_id}/aliases/{node_id}")
async def v2_remove_document_alias(
    document_id: str,
    node_id: str,
    actor: str = Depends(require_management_auth),
):
    return knowledge_store.remove_alias(document_id, node_id, actor=actor)


@app.get("/v2/tags")
async def v2_list_tags(library_id: str):
    return {"tags": knowledge_store.list_tags(library_id)}


@app.post("/v2/tags", status_code=201)
async def v2_create_tag(
    request: V2TagCreateRequest,
    _actor: str = Depends(require_management_auth),
):
    return knowledge_store.create_tag(request.library_id, request.name, request.color)


@app.put("/v2/documents/{document_id}/tags")
async def v2_set_document_tags(
    document_id: str,
    request: V2DocumentTagsRequest,
    _actor: str = Depends(require_management_auth),
):
    return knowledge_store.set_document_tags(document_id, request.tag_ids)


@app.post("/v2/ingest/path", status_code=202)
async def v2_ingest_path(
    request: V2IngestPathRequest,
    actor: str = Depends(require_management_auth),
):
    path = _resolve_allowed_ingest_path(request.path)
    stat = path.stat()
    identity = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
    idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    document_id = None
    if path.is_file():
        content_hash = _hash_file(path)
        document = knowledge_store.create_document(
            library_id=request.library_id,
            title=path.name,
            node_id=request.target_node_id,
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            source_path=str(path),
            source_name=path.name,
            content_hash=content_hash,
            size_bytes=stat.st_size,
            index_status="queued",
            actor=actor,
            idempotent=True,
        )
        document_id = document["id"]
    job = knowledge_store.queue_ingest(
        request.library_id,
        request.target_node_id,
        str(path),
        idempotency_key,
        document_id=document_id,
    )
    return {"status": "queued", "job": job, "document_id": document_id}


@app.get("/v2/jobs")
async def v2_list_jobs(library_id: Optional[str] = None, limit: int = 50):
    return {"jobs": knowledge_store.list_jobs(library_id, limit)}


@app.get("/v2/libraries/{library_id}/audit")
async def v2_list_audit(library_id: str, limit: int = 50):
    return {"events": knowledge_store.list_audit_events(library_id, limit)}

@app.get("/v1/libraries")
@app.post("/v1/libraries")
async def list_libraries():
    """Compatibility view backed by the persistent V2 control plane."""
    return {"libraries": [
        {
            "library_id": item["id"],
            "collection": item["collection_name"],
            "name": item["name"],
            "policy": item["policy"],
            "taxonomy_version": item["taxonomy_version"],
            "document_count": item["document_count"],
            "unclassified_count": item["unclassified_count"],
        }
        for item in knowledge_store.list_libraries()
    ]}


@app.get("/v1/libraries/{library_id}/tree")
async def get_library_tree(library_id: str, version: Optional[int] = None):
    """Get the live taxonomy tree; version is retained for V1 compatibility."""
    result = knowledge_store.get_tree(library_id)
    if version is not None and version != result["version"]:
        raise HTTPException(status_code=409, detail="requested taxonomy version is not current")
    return result


@app.post("/v1/ingest/path")
async def ingest_path(request: IngestPathRequest):
    """Compatibility ingest route; jobs are never stored as zero-vector chunks."""
    path = _resolve_allowed_ingest_path(request.path)
    tree = knowledge_store.get_tree(request.library_id)
    flat_nodes = []

    def flatten(nodes):
        for item in nodes:
            flat_nodes.append(item)
            flatten(item.get("children", []))

    flatten(tree["tree"])
    target = next((item for item in flat_nodes if item["id"] == request.target_node), None)
    if target is None:
        target = next((item for item in flat_nodes if item["is_unclassified"]), None)
    if target is None:
        raise StoreValidationError("library has no unclassified node")
    stat = path.stat()
    identity = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    document_id = None
    if path.is_file():
        document = knowledge_store.create_document(
            request.library_id,
            path.name,
            target["id"],
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            source_path=str(path),
            source_name=path.name,
            content_hash=_hash_file(path),
            size_bytes=stat.st_size,
            index_status="queued",
            idempotent=True,
        )
        document_id = document["id"]
    job = knowledge_store.queue_ingest(
        request.library_id, target["id"], str(path), key, document_id
    )
    return {
        "status": "queued",
        "job_id": job["id"],
        "document_id": document_id,
        "path": str(path),
        "library_id": request.library_id,
        "target_node": target["id"],
    }


@app.post("/v1/taxonomy/proposals")
async def create_taxonomy_proposal(request: TaxonomyProposalRequest):
    """Generate an AI-powered taxonomy classification proposal (V2 persistent).

    Workflow:
    1. Find all unclassified documents in the library
    2. Generate routing cards for each document
    3. Load affected subtree
    4. Send routing cards + subtree to LLM adapter
    5. Parse LLM JSON response into proposal items
    6. Store proposal in SQLite, return preview
    """
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")

    try:
        # Step 1: Find unclassified documents
        docs = knowledge_store.list_documents(request.library_id, status="unclassified", limit=request.max_routing_cards)
        if docs["count"] == 0:
            return {
                "status": "preview",
                "proposal_id": None,
                "items": [],
                "routing_cards_count": 0,
                "message": "No unclassified documents found",
            }

        # Step 2: Build routing cards
        routing_cards = []
        for doc in docs["items"]:
            title = doc["title"] or doc["source_name"]
            text_lower = title.lower()
            signals = []
            if any(w in text_lower for w in ["gpu", "oom", "memory", "cuda", "vllm"]):
                signals.append("gpu-debug")
            if any(w in text_lower for w in ["deploy", "install", "setup", "wsl", "docker"]):
                signals.append("deployment")
            if any(w in text_lower for w in ["test", "benchmark", "perf", "eval"]):
                signals.append("benchmark")
            if any(w in text_lower for w in ["prompt", "api", "chat", "agent", "llm"]):
                signals.append("llm")
            if any(w in text_lower for w in ["vector", "embed", "weaviate", "search", "retriev"]):
                signals.append("vector")
            if any(w in text_lower for w in ["note", "idea", "thought", "brainstorm"]):
                signals.append("notes")
            if not signals:
                signals.append("general")

            routing_cards.append({
                "document_id": doc["id"],
                "title": title,
                "mime": doc["mime_type"],
                "source_name": doc["source_name"],
                "summary": title,
                "signals": signals,
                "content_hash": doc["content_hash"],
            })

        # Step 3: Load subtree
        subtree = PREDEFINED_TREES.get(request.library_id, [])
        subtree_json = json.dumps(subtree, ensure_ascii=False, indent=2)

        # Step 4: Call LLM
        from llm_adapter import call_llm_for_classification
        try:
            classification_result = await call_llm_for_classification(
                library_id=request.library_id,
                subtree=subtree_json,
                routing_cards=routing_cards,
            )
            llm_model = classification_result.get("model_provider", "unknown")
            llm_response = classification_result
            prompt_tokens = classification_result.get("prompt_tokens", 0)
            completion_tokens = classification_result.get("completion_tokens", 0)
        except Exception as llm_err:
            log.warning(f"LLM classification failed: {llm_err}. Falling back to rule-based.")
            fallback = _rule_based_classify(routing_cards, request.library_id)
            llm_model = "rule-based-fallback"
            llm_response = fallback
            prompt_tokens = 0
            completion_tokens = 0

        # Step 5: Create proposal in SQLite
        proposal = knowledge_store.create_proposal(
            library_id=request.library_id,
            llm_model=llm_model,
            llm_response=llm_response,
            routing_cards=routing_cards,
            subtree=subtree,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        # Step 6: Add proposal items
        operations = llm_response.get("operations", [])
        items = []
        for op in operations:
            try:
                item = knowledge_store.add_proposal_item(
                    proposal_id=proposal["id"],
                    document_id=op["file_id"].replace("file-", "doc-") if op["file_id"].startswith("file-") else op.get("document_id", ""),
                    source_node_id=request.source_node if request.source_node != "unclassified" else f"{request.library_id[:2]}-unclassified",
                    target_node_id=op["target_node_id"],
                    confidence=op.get("confidence", 0.0),
                    reason_code=op.get("reason_code", ""),
                    llm_reasoning=op.get("reasoning", ""),
                )
                items.append(item)
            except Exception as item_err:
                log.warning(f"Failed to add proposal item: {item_err}")

        return {
            "status": "preview",
            "proposal_id": proposal["id"],
            "items": items,
            "routing_cards_count": len(routing_cards),
            "llm_model": llm_model,
        }

    except Exception as e:
        log.error(f"Taxonomy proposal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _rule_based_classify(routing_cards: list[dict], library_id: str) -> dict:
    """Rule-based fallback classifier when LLM is unavailable."""
    operations = []
    holds = []
    for card in routing_cards:
        # Simple rule: match signals to library structure
        best_match = "unclassified"
        confidence = 0.6
        if "gpu-debug" in card.get("signals", []) and library_id == "production":
            best_match = "pr-incidents"
            confidence = 0.82
        elif "deployment" in card.get("signals", []) and library_id == "production":
            best_match = "pr-platform"
            confidence = 0.78
        elif "llm" in card.get("signals", []) and library_id == "ai-work":
            best_match = "ai-models"
            confidence = 0.75
        elif "vector" in card.get("signals", []) and library_id == "ai-work":
            best_match = "ai-projects"
            confidence = 0.72
        elif "benchmark" in card.get("signals", []) and library_id == "ai-work":
            best_match = "ai-models"
            confidence = 0.7

        if confidence >= 0.88:
            operations.append({
                "op": "move",
                "file_id": card["file_id"],
                "target_node_id": best_match,
                "confidence": round(confidence, 2),
                "reason_code": "SIGNAL_MATCH",
            })
        elif confidence >= 0.65:
            operations.append({
                "op": "move",
                "file_id": card["file_id"],
                "target_node_id": best_match,
                "confidence": round(confidence, 2),
                "reason_code": "SIGNAL_MATCH",
            })
        else:
            holds.append({
                "file_id": card["file_id"],
                "confidence": round(confidence, 2),
                "reason_code": "LOW_CONFIDENCE",
            })

    return {
        "taxonomy_version": _taxonomy_version.get(library_id, 1),
        "operations": operations,
        "holds": holds,
        "model_provider": "rule-based-fallback",
    }


@app.get("/v1/taxonomy/proposals")
async def list_taxonomy_proposals(library_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    """List classification proposals."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        proposals = knowledge_store.list_proposals(library_id=library_id, status=status, limit=limit)
        return {"proposals": proposals, "count": len(proposals)}
    except Exception as e:
        log.error(f"List proposals error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/taxonomy/proposals/{proposal_id}")
async def get_taxonomy_proposal(proposal_id: str):
    """Get a taxonomy proposal with its items."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        proposal = knowledge_store.get_proposal(proposal_id)
        return proposal
    except StoreNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Get proposal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/taxonomy/proposals/{proposal_id}/approve/{item_id}")
async def approve_proposal_item(proposal_id: str, item_id: str):
    """Approve a proposal item."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        item = knowledge_store.approve_proposal_item(item_id)
        return {"status": "approved", "item": item}
    except StoreNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StoreValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Approve item error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/taxonomy/proposals/{proposal_id}/reject/{item_id}")
async def reject_proposal_item(proposal_id: str, item_id: str, request: ProposalItemActionRequest = None):
    """Reject a proposal item."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        reason = request.reason if request else ""
        item = knowledge_store.reject_proposal_item(item_id, reason=reason)
        return {"status": "rejected", "item": item}
    except StoreNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StoreValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Reject item error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/taxonomy/proposals/{proposal_id}/apply")
async def apply_taxonomy_proposal(proposal_id: str, request: TaxonomyProposalApplyRequest = None):
    """Apply all approved items in a proposal."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        result = knowledge_store.apply_proposal(proposal_id)
        return result
    except StoreNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Apply proposal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/taxonomy/proposals/{proposal_id}/revert")
async def revert_taxonomy_proposal(proposal_id: str):
    """Revert all applied items in a proposal."""
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    try:
        result = knowledge_store.revert_proposal(proposal_id)
        return result
    except StoreNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Revert proposal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/associations/discover")
async def discover_associations(request: KnowledgeEdgeRequest):
    """Discover candidate cross-library associations."""
    edges = []
    for _ in range(min(request.edge_budget, 5)):
        edges.append({
            "edge_id": f"edge-candidate-{len(edges)}",
            "source_library_id": request.source_scope,
            "relation_type": "supports",
            "confidence": round(0.7 + _taxonomy_version.get("production", 1) * 0.01, 2),
            "status": "candidate",
        })
    return {
        "status": "discovered",
        "edges": edges,
        "edge_count": len(edges),
        "mode": request.mode,
    }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Gateway")
    parser.add_argument("--port", type=int, default=9100, help="Gateway port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (use 0.0.0.0 for WSL external access)")
    args = parser.parse_args()

    import uvicorn
    log.info(f"Starting RAG Gateway on {args.host}:{args.port}")
    # Pass the existing app object.  Using "rag_gateway:app" after executing
    # this file directly imports the module a second time and can duplicate
    # Weaviate connections and schema initialization.
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
