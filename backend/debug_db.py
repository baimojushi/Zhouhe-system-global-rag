#!/usr/bin/env python3
"""Debug database content."""
import sys; sys.path.insert(0, '/opt/global-rag/backend')
from knowledge_store import KnowledgeStore

store = KnowledgeStore('/opt/global-rag/data/control.db')

# Check libraries
libs = store.list_libraries()
print(f'Libraries: {len(libs)}')
for l in libs:
    if isinstance(l, dict):
        print(f'  id={l.get("id")} name={l.get("name")}')
    else:
        print(f'  {l}')

# Find academic library
acad_id = None
for l in libs:
    if isinstance(l, dict) and '学术' in l.get('name', ''):
        acad_id = l['id']
        break
print(f'Academic library ID: {acad_id}')

if acad_id:
    result = store.list_documents(library_id=acad_id, limit=100)
    docs = result.get('items', result) if isinstance(result, dict) else result
    print(f'Documents in academic: {len(docs) if isinstance(docs,list) else docs}')
    
    # Also check all docs directly
    conn = store._connect()
    all_docs = conn.execute('SELECT id, library_id, source_path, source_name FROM documents').fetchall()
    print(f'\nAll documents in DB: {len(all_docs)}')
    for d in all_docs:
        print(f'  {d["id"][:20]}: lib={d["library_id"]} name={d["source_name"][:60]}')
    conn.close()
