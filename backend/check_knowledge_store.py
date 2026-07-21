#!/usr/bin/env python3
"""Check knowledge_store database."""
import sys
sys.path.insert(0, "/opt/global-rag")

from knowledge_store import KnowledgeStore

store = KnowledgeStore("/opt/global-rag/data/knowledge-control.db")
conn = store._connect()

# Check documents table
rows = conn.execute("SELECT * FROM documents LIMIT 5").fetchall()
print(f"Documents: {len(rows)}")
for row in rows:
    print(f"  id={row['id']}, library_id={row['library_id']}, current_version_id={row['current_version_id']}, index_status={row['index_status']}")

# Check document_versions table
rows2 = conn.execute("SELECT * FROM document_versions LIMIT 5").fetchall()
print(f"\nDocument versions: {len(rows2)}")
for row in rows2:
    print(f"  id={row['id']}, index_status={row['index_status']}")

conn.close()
