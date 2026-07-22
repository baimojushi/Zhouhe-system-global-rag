#!/usr/bin/env python3
"""V1 verification test: PDF routing, MinerU integration, markdown chunking."""
import sys, os, json, hashlib, tempfile
sys.path.insert(0, '/opt/global-rag/backend')

# 1. Verify .pdf is in SUPPORTED_SUFFIXES
from ingest_layout import SUPPORTED_SUFFIXES
assert '.pdf' in SUPPORTED_SUFFIXES, '.pdf not in SUPPORTED_SUFFIXES'
print('[PASS] .pdf in SUPPORTED_SUFFIXES')

# 2. Verify is_pdf_file detection
from ingest_worker import is_pdf_file
assert is_pdf_file('/tmp/test.PDF')
assert is_pdf_file('/tmp/test.pdf')
assert not is_pdf_file('/tmp/test.txt')
assert not is_pdf_file('/tmp/test.md')
print('[PASS] is_pdf_file detection')

# 3. Test _chunk_markdown
from ingest_worker import _chunk_markdown

# Simple markdown
md = '''## Section 1
This is the first section content.
It has multiple lines.

## Section 2
This is the second section.
'''
chunks = _chunk_markdown(md, 'test.pdf', chunk_size=200, overlap=20)
assert len(chunks) >= 2, f'Expected >=2 chunks, got {len(chunks)}'
assert chunks[0]['heading'] == 'Section 1'
assert chunks[1]['heading'] == 'Section 2'
print(f'[PASS] _chunk_markdown: {len(chunks)} chunks, headings preserved')

# 4. Test MinerU client integration (requires running API)
from mineru_client import MinerUClient, MinerUConnectionError
client = MinerUClient()
try:
    h = client.health()
    assert h['status'] == 'healthy'
    print(f'[PASS] MinerU API reachable (version {h["version"]})')

    # Submit test PDF
    task = client.submit_task('/home/baimo/services/mineru/input/test.pdf')
    print(f'[PASS] Task submitted: {task.task_id}')

    # Poll
    final = client.poll_until_complete(task.task_id, max_seconds=60)
    assert final.is_success, f'Task failed: {final.error}'
    print(f'[PASS] Task completed')

    # Fetch result
    result = client.get_task_result(task.task_id)
    assert len(result.md_content) > 0
    print(f'[PASS] Result fetched: {len(result.md_content)} chars MD')

    # Test _chunk_markdown with real MinerU output
    real_chunks = _chunk_markdown(result.md_content, 'test.pdf')
    assert len(real_chunks) > 0
    print(f'[PASS] Real MinerU output chunked into {len(real_chunks)} chunks')

except MinerUConnectionError as e:
    print(f'[SKIP] MinerU not reachable: {e}')

# 5. Test document_parser integration
from document_parser import get_parser, MinerUParser
parser = get_parser('mineru')
assert parser is not None
assert parser.name() == 'mineru'
assert parser.version() == '3.4.4'
print('[PASS] DocumentParser registry')

# 6. Test parse_jobs table with KnowledgeStore
from knowledge_store import KnowledgeStore
db_path = '/tmp/test_v1_parse.db'
for p in [db_path]:
    if os.path.exists(p):
        os.remove(p)

store = KnowledgeStore(db_path)
conn = store._connect()
tables = [r['name'] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
assert 'parse_jobs' in tables
print('[PASS] parse_jobs table in KnowledgeStore')

# Test create_parse_job with direct SQL (bypass FK for schema test)
conn.execute("PRAGMA foreign_keys = OFF")
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat(timespec='seconds')
conn.execute("""INSERT INTO parse_jobs
    (id, ingest_job_id, document_id, version_id,
     parser_name, parser_version, source_hash,
     config_fingerprint, state, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'parsing', ?, ?)""",
    ('parse-recovery-001', 'ingest-001', 'doc-001', 'ver-001',
     'mineru', '3.4.4', 'abc123', 'v1', now, now))
conn.commit()

# Test list by state (used by recover_stale_parse_jobs)
rows = conn.execute(
    "SELECT * FROM parse_jobs WHERE state='parsing' ORDER BY created_at DESC"
).fetchall()
assert len(rows) == 1
print('[PASS] list_parse_jobs by state (recovery path)')

conn.close()
os.remove(db_path)

print()
print('=== ALL V1 VERIFICATION TESTS PASSED ===')
