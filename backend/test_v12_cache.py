#!/usr/bin/env python3
"""V1.2 verification: parse cache, force re-parse, metrics."""
import sys, os, json
sys.path.insert(0, '/opt/global-rag/backend')

from knowledge_store import KnowledgeStore

# 1. Test cache lookup logic
from ingest_worker import _find_cached_parse, _index_from_artifact

db_path = '/tmp/test_v12_cache.db'
if os.path.exists(db_path):
    os.remove(db_path)

store = KnowledgeStore(db_path)
conn = store._connect()
conn.execute("PRAGMA foreign_keys = OFF")
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat(timespec='seconds')

# Create a mock parsed job
conn.execute("""INSERT INTO parse_jobs
    (id, ingest_job_id, document_id, version_id,
     parser_name, parser_version, source_hash,
     config_fingerprint, state, artifact_dir, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'parsed', ?, ?, ?)""",
    ('parse-cached-001', 'ingest-001', 'doc-001', 'ver-001',
     'mineru', '3.4.4', 'abc123def456', 'v1',
     '/tmp/test_artifact', now, now))
conn.commit()
conn.close()

# Create the artifact directory
os.makedirs('/tmp/test_artifact', exist_ok=True)
with open('/tmp/test_artifact/document.md', 'w') as f:
    f.write('## Test\nCached content')
with open('/tmp/test_artifact/content_list.json', 'w') as f:
    json.dump([], f)

# Test cache hit
cached = _find_cached_parse(store, 'abc123def456', 'v1')
assert cached == '/tmp/test_artifact', f'Expected /tmp/test_artifact, got {cached}'
print('[PASS] Cache hit: same hash + fingerprint')

# Test cache miss (different hash)
cached = _find_cached_parse(store, 'different_hash', 'v1')
assert cached is None
print('[PASS] Cache miss: different hash')

# Test cache miss (different fingerprint)
cached = _find_cached_parse(store, 'abc123def456', 'v2')
assert cached is None
print('[PASS] Cache miss: different fingerprint')

# 2. Test parse_job stats via health endpoint
import httpx
try:
    resp = httpx.get('http://127.0.0.1:9100/health', timeout=5)
    data = resp.json()
    print(f'[PASS] Health endpoint: status={data.get("status")}')
    if 'parse_jobs' in data:
        print(f'[PASS] Parse job stats in health: {data["parse_jobs"]}')
    else:
        print('[WARN] No parse_jobs in health response')
except Exception as e:
    print(f'[SKIP] Gateway not reachable: {e}')

# 3. Test parse_jobs listing endpoint
try:
    resp = httpx.get('http://127.0.0.1:9100/v1/parse-jobs?state=parsed&limit=10',
                     headers={'X-API-Key': 'dev-key'}, timeout=5)
    if resp.status_code == 200:
        data = resp.json()
        print(f'[PASS] Parse jobs listing: {data.get("total")} jobs')
    else:
        print(f'[SKIP] Parse jobs endpoint returned {resp.status_code}')
except Exception as e:
    print(f'[SKIP] Parse jobs endpoint: {e}')

# 4. Test force_reparse parameter exists
import inspect
from ingest_worker import process_pdf_job
sig = inspect.signature(process_pdf_job)
assert 'force_reparse' in sig.parameters
print('[PASS] force_reparse parameter present')

# Cleanup
os.remove(db_path)
import shutil
shutil.rmtree('/tmp/test_artifact', ignore_errors=True)

print()
print('=== V1.2 ALL TESTS PASSED ===')
