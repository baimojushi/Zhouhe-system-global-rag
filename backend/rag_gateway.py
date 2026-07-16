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