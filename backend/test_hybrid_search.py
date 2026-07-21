#!/usr/bin/env python3
"""Test hybrid_search function directly."""
import sys
sys.path.insert(0, "/opt/global-rag")

from rag_gateway import hybrid_search

print("Testing hybrid_search...")
results = hybrid_search("摄取端到端测试", top_k=5, alpha=0.7, active_versions_only=True)
print(f"Results: {len(results)}")
for r in results:
    print(f"  source_name: {r.get('source_name', 'N/A')}")
    print(f"  title: {r.get('title', 'N/A')}")
    print(f"  content: {r.get('content', '')[:100]}...")
    print(f"  score: {r.get('score', 'N/A')}")
    print()
