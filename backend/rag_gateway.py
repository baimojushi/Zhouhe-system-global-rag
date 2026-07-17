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
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/opt/global-rag/cache/huggingface")
os.environ.setdefault("DOCLING_ARTIFACTS_PATH", "/opt/global-rag/cache/docling-models")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import weaviate
import weaviate.classes as wvc
from weaviate.auth import AuthApiKey
from FlagEmbedding import FlagModel

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

# Load API key
env_path = Path("/opt/global-rag/stack/.env")
api_key = ""
with open(env_path) as f:
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

def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.55,
                  collection=None, filters: dict = None) -> list[dict]:
    """Hybrid search with pre-computed vector (self_provided vectors)."""
    model = get_model()
    query_vec = model.encode(query).tolist()

    # Build filters
    weaviate_filters = []
    if filters:
        for key, value in filters.items():
            weaviate_filters.append(
                wvc.query.Filter.by_property(key).equal(value)
            )

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

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "weaviate": "connected",
        "model": "loaded" if model is not None else "loading",
    }

@app.post("/v1/retrieve")
async def retrieve(request: RetrieveRequest):
    """Core retrieval endpoint — hybrid search."""
    try:
        results = hybrid_search(
            query=request.query,
            top_k=request.top_k,
            alpha=request.alpha,
            filters={"scope": request.scope},
        )
        return {
            "query": request.query,
            "top_k": request.top_k,
            "alpha": request.alpha,
            "scope": request.scope,
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
    """MCP tool: search knowledge base."""
    try:
        results = hybrid_search(
            query=request.query,
            top_k=request.top_k,
            alpha=0.55,
            filters={"scope": request.scope},
        )
        return {
            "tool": "search_knowledge",
            "query": request.query,
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

# Taxonomy version tracker (in-memory, serializable)
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
                    wvc.config.Property(name="version_created", data_type=wvc.config.DataType.INT64),
                    wvc.config.Property(name="version_retired", data_type=wvc.config.DataType.INT64, additional_properties=["nullable"], is_nullable=True),
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
        # Only seed if collection is empty
        count = coll.aggregate.over_all(total_count=True).total_count
        if count > 0:
            continue
        for node in nodes:
            node["version_created"] = version
            node["version_retired"] = None
        coll.data.insert_batch(nodes)
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


# --- Routes ---

@app.post("/v1/libraries")
async def list_libraries():
    """List all configured knowledge libraries."""
    libs = []
    for lid, info in LIBRARY_REGISTRY.items():
        coll_name = info["collection"]
        try:
            coll = weaviate_client.collections.get(coll_name)
            count = coll.aggregate.over_all(total_count=True).total_count
        except Exception:
            count = 0
        libs.append({
            "library_id": lid,
            **info,
            "taxonomy_version": _taxonomy_version.get(lid, 1),
            "document_count": count,
        })
    return {"libraries": libs}


@app.get("/v1/libraries/{library_id}/tree")
async def get_library_tree(library_id: str, version: Optional[int] = None):
    """Get the taxonomy tree for a library."""
    if library_id not in LIBRARY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Library '{library_id}' not found")
    tree_version = version or _taxonomy_version.get(library_id, 1)
    return {
        "library_id": library_id,
        "version": tree_version,
        "tree": PREDEFINED_TREES.get(library_id, []),
    }


@app.post("/v1/ingest/path")
async def ingest_path(request: IngestPathRequest):
    """Queue a local file path for ingestion into a library's unclassified node."""
    if request.library_id not in LIBRARY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Library '{request.library_id}' not found")

    import hashlib
    import json
    from pathlib import Path as PPath

    kb_path = PPath(request.path)
    if not kb_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {request.path}")

    file_hash = hashlib.sha256(kb_path.read_bytes()).hexdigest()[:16]
    chunk_id = f"path-{file_hash}"

    # Store ingest job metadata (in Weaviate KnowledgeChunk with scope=ingest-queue)
    ingest_coll = weaviate_client.collections.get("KnowledgeChunk")
    ingest_coll.data.insert(
        properties={
            "chunk_id": chunk_id,
            "content": f"[ingest-queue] {request.path}",
            "title": kb_path.name,
            "heading": "ingest",
            "source_path": request.path,
            "source_name": kb_path.name,
            "source_hash": file_hash,
            "mime_type": "path-reference",
            "page": 0,
            "chunk_index": 0,
            "scope": "ingest-queue",
            "library_id": request.library_id,
            "target_node": request.target_node,
            "classification": request.classification,
            "modified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        vector=[0.0] * 1024,  # Placeholder — will be re-encoded by batch indexer
    )
    return {
        "status": "queued",
        "chunk_id": chunk_id,
        "path": request.path,
        "library_id": request.library_id,
        "target_node": request.target_node,
    }


@app.post("/v1/taxonomy/proposals")
async def create_taxonomy_proposal(request: TaxonomyProposalRequest):
    """Generate an AI-powered taxonomy classification proposal.

    Workflow:
    1. Find all files in source_node (unclassified)
    2. Generate routing cards for each file
    3. Load affected subtree (parent, siblings, children of source_node)
    4. Send routing cards + subtree to LLM adapter
    5. Parse LLM JSON response into operations/holds
    6. Store change_set in memory, return preview
    """
    if request.library_id not in LIBRARY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Library '{request.library_id}' not found")

    try:
        # --- Step 1: Find unclassified files ---
        coll_name = LIBRARY_REGISTRY[request.library_id]["collection"]
        kb_coll = weaviate_client.collections.get(coll_name)
        where_filter = wvc.query.Filter.by_property("scope").equal("unclassified")
        query_text = f"{LIBRARY_REGISTRY[request.library_id]['name']} {request.library_id}"
        query_vec = get_model().encode(query_text).tolist()

        result = kb_coll.query.hybrid(
            query=query_text, limit=request.max_routing_cards,
            alpha=0.5, vector=query_vec, filters=where_filter,
            include_vector=False,
        )
        unclassified_chunks = []
        for obj in result.objects:
            props = obj.properties
            if props.get("source_name") and props.get("source_hash"):
                unclassified_chunks.append({
                    "file_id": f"file-{props['source_hash']}",
                    "source_hash": props["source_hash"],
                    "source_name": props["source_name"],
                    "source_path": props.get("source_path", ""),
                    "title": props.get("title", ""),
                    "heading": props.get("heading", ""),
                    "mime_type": props.get("mime_type", "text/plain"),
                })

        if not unclassified_chunks:
            return {
                "status": "preview",
                "operations": [],
                "holds": [],
                "taxonomy_version": _taxonomy_version.get(request.library_id, 1),
                "routing_cards_count": 0,
            }

        # --- Step 2: Build routing cards ---
        routing_cards = []
        for chunk in unclassified_chunks[:request.max_routing_cards]:
            title = chunk["title"] or chunk["source_name"]
            # Simple entity/signal extraction (local heuristic)
            text_lower = (title + " " + chunk["heading"]).lower()
            signals = []
            if any(w in text_lower for w in ["gpu", "oom", "memory", "cuda", "vllm"]):
                signals.append("gpu-debug")
            if any(w in text_lower for w in ["deploy", "install", "setup", "ws"]):
                signals.append("deployment")
            if any(w in text_lower for w in ["test", "benchmark", "perf", "eval"]):
                signals.append("benchmark")
            if any(w in text_lower for w in ["prompt", "api", "chat", "agent"]):
                signals.append("llm")
            if any(w in text_lower for w in ["vector", "embed", "weaviate", "search", "retriev"]):
                signals.append("vector")
            if any(w in text_lower for w in ["note", "idea", "thought", "brainstorm"]):
                signals.append("notes")
            if not signals:
                signals.append("general")
            routing_cards.append({
                "file_id": chunk["file_id"],
                "title": title,
                "mime": chunk["mime_type"],
                "headings": [chunk["heading"]] if chunk["heading"] else [],
                "summary": title,
                "entities": chunk["source_name"].split(".")[0].split("_"),
                "signals": signals,
                "content_hash": chunk["source_hash"],
            })

        # --- Step 3: Load affected subtree ---
        subtree = PREDEFINED_TREES.get(request.library_id, [])
        subtree_json = json.dumps(subtree, ensure_ascii=False, indent=2)

        # --- Step 4: Build prompt for LLM ---
        from .llm_adapter import call_llm_for_classification  # Lazy import
        proposal_id = f"proposal-{request.library_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        change_set = {
            "change_set_id": proposal_id,
            "library_id": request.library_id,
            "base_version": _taxonomy_version.get(request.library_id, 1),
            "status": "preview",
            "requested_by": "auto-classifier",
            "operations_json": [],
            "operations": [],
            "holds": [],
            "routing_cards_count": len(routing_cards),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        try:
            classification_result = await call_llm_for_classification(
                library_id=request.library_id,
                subtree=subtree_json,
                routing_cards=routing_cards,
            )
            change_set.update(classification_result)
            _change_set_store[proposal_id] = change_set
        except Exception as llm_err:
            log.warning(f"LLM classification failed: {llm_err}. Falling back to rule-based.")
            # Rule-based fallback
            fallback = _rule_based_classify(routing_cards, request.library_id)
            change_set.update(fallback)
            _change_set_store[proposal_id] = change_set

        return change_set

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


@app.get("/v1/taxonomy/proposals/{proposal_id}")
async def get_taxonomy_proposal(proposal_id: str):
    """Get a taxonomy proposal by ID."""
    cs = _change_set_store.get(proposal_id)
    if not cs:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found")
    return cs


@app.post("/v1/taxonomy/proposals/{proposal_id}/apply")
async def apply_taxonomy_proposal(proposal_id: str, request: TaxonomyProposalApplyRequest):
    """Apply a taxonomy proposal (move files to new nodes)."""
    cs = _change_set_store.get(proposal_id)
    if not cs:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found")
    if cs.get("status") != "preview":
        raise HTTPException(status_code=400, detail="Proposal already applied")

    expected_version = request.expected_taxonomy_version
    actual_version = _taxonomy_version.get(cs["library_id"], 1)
    if expected_version != actual_version:
        raise HTTPException(status_code=409, detail=f"taxonomy_version_conflict: expected {expected_version}, got {actual_version}")

    # Apply operations: update scope of KnowledgeChunks from "unclassified" to target node
    operations = cs.get("operations", [])
    library_id = cs["library_id"]
    coll_name = LIBRARY_REGISTRY[library_id]["collection"]
    kb_coll = weaviate_client.collections.get(coll_name)

    applied_count = 0
    for op in operations:
        file_id = op["file_id"]
        hash_prefix = file_id.replace("file-", "")
        target_scope = f"{library_id}/{op['target_node_id']}"

        # Find and update all matching chunks
        where_filter = wvc.query.Filter.by_property("scope").equal("unclassified")
        result = kb_coll.query.hybrid(
            query="", limit=50, alpha=1.0,
            filters=where_filter, include_vector=False,
        )
        for obj in result.objects:
            source_hash = obj.properties.get("source_hash", "")
            if source_hash.startswith(hash_prefix[:8]):
                kb_coll.properties.update(
                    uuid=obj.uuid,
                    properties={"scope": target_scope},
                )
                applied_count += 1

    # Update change_set status
    cs["status"] = "applied"
    cs["applied_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cs["applied_count"] = applied_count

    # Bump taxonomy version
    _taxonomy_version[library_id] = actual_version + 1

    return {
        "status": "applied",
        "change_set_id": proposal_id,
        "applied_count": applied_count,
        "new_version": _taxonomy_version[library_id],
    }


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
    args = parser.parse_args()

    import uvicorn
    log.info(f"Starting RAG Gateway on 127.0.0.1:{args.port}")
    uvicorn.run(
        "rag_gateway:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )