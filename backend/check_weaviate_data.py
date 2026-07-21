#!/usr/bin/env python3
"""Check Weaviate data after ingest."""
import sys
sys.path.insert(0, "/opt/global-rag")

import weaviate
from weaviate.auth import AuthApiKey

API_KEY = "1c95b235989f7ef61fdb2c73513ab8e1d9bb750094c30d11f4d506de3acacf1e"

client = weaviate.connect_to_local(
    host="localhost", port=8080, grpc_port=50051,
    auth_credentials=AuthApiKey(API_KEY),
)

# Check all collections
collections = list(client.collections.list_all().keys())
print(f"Collections: {collections}")

# Check Kb_production_v1
for coll_name in collections:
    if coll_name.startswith("Kb_"):
        print(f"\n--- {coll_name} ---")
        collection = client.collections.get(coll_name)
        response = collection.query.fetch_objects(limit=5)
        print(f"Objects count: {len(response.objects)}")
        for obj in response.objects:
            props = obj.properties
            print(f"  source_name: {props.get('source_name', 'N/A')}")
            print(f"  title: {props.get('title', 'N/A')}")
            content = props.get("content", "")
            print(f"  content: {content[:100]}...")
            print()

# Also check KnowledgeChunk
print("\n--- KnowledgeChunk ---")
try:
    collection = client.collections.get("KnowledgeChunk")
    response = collection.query.fetch_objects(limit=5)
    print(f"Objects count: {len(response.objects)}")
    for obj in response.objects:
        props = obj.properties
        print(f"  source_name: {props.get('source_name', 'N/A')}")
        print(f"  title: {props.get('title', 'N/A')}")
        content = props.get("content", "")
        print(f"  content: {content[:100]}...")
        print()
except Exception as e:
    print(f"Error: {e}")

client.close()
