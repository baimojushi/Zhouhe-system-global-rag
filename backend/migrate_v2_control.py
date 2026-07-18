#!/usr/bin/env python3
"""Bootstrap V2 Document records from existing Weaviate KnowledgeChunk data.

The migration is idempotent and never edits or deletes Weaviate objects.  Run
with --dry-run first, back up Weaviate and the control database, then run again
without --dry-run.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path

import weaviate
from weaviate.auth import AuthApiKey

from knowledge_store import KnowledgeStore


def load_api_key() -> str:
    key = os.environ.get("WEAVIATE_API_KEY", "").strip()
    env_path = Path("/opt/global-rag/stack/.env")
    if not key and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("WEAVIATE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                break
    if not key:
        raise RuntimeError("WEAVIATE_API_KEY is not configured")
    return key


def unclassified_nodes(store: KnowledgeStore) -> dict[str, str]:
    result: dict[str, str] = {}

    def walk(library_id: str, nodes: list[dict]):
        for node in nodes:
            if node.get("is_unclassified"):
                result[library_id] = node["id"]
            walk(library_id, node.get("children", []))

    for library in store.list_libraries():
        walk(library["id"], store.get_tree(library["id"])["tree"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate existing chunks to V2 control records")
    parser.add_argument("--database", default=os.environ.get(
        "RAG_CONTROL_DB", "/opt/global-rag/data/knowledge-control.db"
    ))
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--grpc-port", type=int, default=50051)
    parser.add_argument("--source-collection", default="KnowledgeChunk")
    parser.add_argument("--default-library", default="production")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    store = KnowledgeStore(args.database)
    libraries = {item["id"] for item in store.list_libraries()}
    if args.default_library not in libraries:
        raise RuntimeError(f"default library '{args.default_library}' does not exist")
    inbox = unclassified_nodes(store)

    client = weaviate.connect_to_local(
        host=args.host,
        port=args.http_port,
        grpc_port=args.grpc_port,
        auth_credentials=AuthApiKey(load_api_key()),
    )
    grouped: dict[tuple[str, str, str], dict] = {}
    per_library = defaultdict(int)
    try:
        collection = client.collections.get(args.source_collection)
        for obj in collection.iterator(include_vector=False):
            props = obj.properties or {}
            source_path = str(props.get("source_path") or "")
            source_name = str(props.get("source_name") or Path(source_path).name or "未命名文档")
            source_hash = str(props.get("source_hash") or props.get("content_hash") or "")
            library_id = str(props.get("library_id") or args.default_library)
            if library_id not in libraries or library_id == "association":
                library_id = args.default_library
            key = (library_id, source_path or source_name, source_hash)
            if key not in grouped:
                grouped[key] = {
                    "library_id": library_id,
                    "title": str(props.get("title") or source_name),
                    "source_path": source_path,
                    "source_name": source_name,
                    "content_hash": source_hash,
                    "mime_type": str(props.get("mime_type") or "application/octet-stream"),
                }

        for record in grouped.values():
            per_library[record["library_id"]] += 1
            if args.dry_run:
                continue
            store.create_document(
                library_id=record["library_id"],
                title=record["title"],
                node_id=inbox[record["library_id"]],
                mime_type=record["mime_type"],
                source_path=record["source_path"],
                source_name=record["source_name"],
                content_hash=record["content_hash"],
                index_status="indexed",
                actor="v2-migration",
                idempotent=True,
            )
    finally:
        client.close()

    action = "would create/check" if args.dry_run else "created/checked"
    print(f"V2 migration {action} {len(grouped)} document records")
    for library_id in sorted(per_library):
        print(f"  {library_id}: {per_library[library_id]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
