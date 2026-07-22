#!/usr/bin/env python3
"""V0 verification test for parse_jobs table schema and basic operations."""
import sys
sys.path.insert(0, '/opt/global-rag/backend')

from knowledge_store import KnowledgeStore, SCHEMA_VERSION
print('Schema version:', SCHEMA_VERSION)

import os, sqlite3
db_path = '/tmp/test_v0_parse.db'
for p in [db_path, '/tmp/test_v0_parse_2.db']:
    if os.path.exists(p):
        os.remove(p)

# 1. Verify table exists in schema
store = KnowledgeStore(db_path)
conn = store._connect()
tables = [r['name'] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
print('Tables:', sorted(tables))
assert 'parse_jobs' in tables, 'parse_jobs table not created!'
print('[PASS] parse_jobs table exists')

# 2. Verify table columns
cols = [dict(r) for r in conn.execute("PRAGMA table_info(parse_jobs)").fetchall()]
col_names = [c['name'] for c in cols]
print('parse_jobs columns:', col_names)
expected = ['id', 'ingest_job_id', 'document_id', 'version_id',
            'parser_name', 'parser_version', 'external_task_id',
            'source_hash', 'config_fingerprint', 'state', 'progress',
            'artifact_dir', 'manifest_json', 'submit_attempts',
            'poll_failures', 'error', 'created_at', 'updated_at']
for col in expected:
    assert col in col_names, f'Missing column: {col}'
print('[PASS] All expected columns present')

# 3. Test direct SQL insert/select (bypass FK for schema test)
conn.execute("PRAGMA foreign_keys = OFF")
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat(timespec='seconds')
conn.execute("""INSERT INTO parse_jobs
    (id, ingest_job_id, document_id, version_id,
     parser_name, parser_version, source_hash,
     config_fingerprint, state, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
    ('parse-001', 'ingest-001', 'doc-001', 'ver-001',
     'mineru', '3.4.4', 'abc123', 'cfg-v1', now, now))
conn.commit()

row = dict(conn.execute("SELECT * FROM parse_jobs WHERE id='parse-001'").fetchone())
assert row['state'] == 'queued'
assert row['parser_name'] == 'mineru'
assert row['parser_version'] == '3.4.4'
print('[PASS] Direct INSERT/SELECT works')

# 4. Test update
conn.execute("""UPDATE parse_jobs SET state='parsing',
    external_task_id='mineru-task-001', updated_at=? WHERE id=?""",
    (now, 'parse-001'))
conn.commit()
row = dict(conn.execute("SELECT * FROM parse_jobs WHERE id='parse-001'").fetchone())
assert row['state'] == 'parsing'
assert row['external_task_id'] == 'mineru-task-001'
print('[PASS] UPDATE works')

# 5. Test list by state
rows = conn.execute(
    "SELECT * FROM parse_jobs WHERE state='parsing' ORDER BY created_at DESC"
).fetchall()
assert len(rows) == 1
print('[PASS] List by state works')

# 6. Test get by external_task_id
row = conn.execute(
    "SELECT * FROM parse_jobs WHERE external_task_id='mineru-task-001'"
).fetchone()
assert row is not None
print('[PASS] Get by external_task_id works')

conn.close()

# 7. Test with fresh DB to verify migration creates table
store2 = KnowledgeStore('/tmp/test_v0_parse_2.db')
conn2 = store2._connect()
tables2 = [r['name'] for r in conn2.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
assert 'parse_jobs' in tables2
print('[PASS] Fresh DB migration creates parse_jobs table')
conn2.close()

# Cleanup
os.remove(db_path)
os.remove('/tmp/test_v0_parse_2.db')

print()
print('=== ALL V0 TESTS PASSED ===')
