#!/usr/bin/env python3
"""Search for e2e-test document in Weaviate."""
import sys
sys.path.insert(0, "/opt/global-rag")

import weaviate
from weaviate.auth import AuthApiKey

API_KEY = "1c95b235989f7ef61fdb2c73513ab8e1d9bb750094c30d11f4d506de3acacf1e"

client = weaviate.connect_to_local(
    host="localhost", port=8080, grpc_port=50051,
    auth_credentials=AuthApiKey(API_KEY),
)

# Search in Kb_production_v1
print("=== Searching Kb_production_v1 ===")
collection = client.collections.get("Kb_production_v1")

# Fetch all objects
response = collection.query.fetch_objects(limit=100)
print(f"Total objects in Kb_production_v1: {len(response.objects)}")

found = False
for obj in response.objects:
    props = obj.properties
    source_name = props.get("source_name", "")
    title = props.get("title", "")
    content = props.get("content", "")
    if "e2e-test" in source_name or "e2e-test" in title or "端到端测试" in content:
        print(f"\n[FOUND] e2e-test document!")
        print(f"  source_name: {source_name}")
        print(f"  title: {title}")
        print(f"  content: {content[:200]}...")
        found = True

if not found:
    print("\n[NOT FOUND] e2e-test document not found in Kb_production_v1")

# Also search in KnowledgeChunk
print("\n=== Searching KnowledgeChunk ===")
collection2 = client.collections.get("KnowledgeChunk")
response2 = collection2.query.fetch_objects(limit=100)
print(f"Total objects in KnowledgeChunk: {len(response2.objects)}")

found2 = False
for obj in response2.objects:
    props = obj.properties
    source_name = props.get("source_name", "")
    title = props.get("title", "")
    content = props.get("content", "")
    if "e2e-test" in source_name or "e2e-test" in title or "端到端测试" in content:
        print(f"\n[FOUND] e2e-test document!")
        print(f"  source_name: {source_name}")
        print(f"  title: {title}")
        print(f"  content: {content[:200]}...")
        found2 = True

if not found2:
    print("\n[NOT FOUND] e2e-test document not found in KnowledgeChunk")

client.close()
