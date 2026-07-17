#!/usr/bin/env python3
"""Quick test: import rag_gateway and check health."""
import os
import sys
sys.path.insert(0, "/opt/global-rag")

print("Step 1: Importing weaviate...")
import weaviate
print(f"  weaviate version: {weaviate.__version__}")

print("Step 2: Importing FlagEmbedding...")
from FlagEmbedding import FlagModel
print(f"  FlagEmbedding version OK")

print("Step 3: Importing fastapi...")
from fastapi import FastAPI
print(f"  FastAPI OK")

print("Step 4: Testing Weaviate connection...")
api_key = os.environ.get("WEAVIATE_API_KEY")
if not api_key:
    print("  Weaviate ERROR: set WEAVIATE_API_KEY before running this test")
    sys.exit(2)

try:
    client = weaviate.connect_to_local(
        host="localhost", port=8080, grpc_port=50051,
        auth_credentials=weaviate.auth.AuthApiKey(api_key),
    )
    meta = client.meta
    print(f"  Weaviate connected: {meta.name} v{meta.version}")
    collections = client.collections.list_all()
    print(f"  Collections: {list(collections.keys())}")
    client.close()
except Exception as e:
    print(f"  Weaviate ERROR: {e}")
    sys.exit(1)

print("Step 5: Done - all imports OK")
