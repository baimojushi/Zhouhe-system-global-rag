#!/usr/bin/env python3
"""Integration test for MinerU client against running API."""
import sys
sys.path.insert(0, '/opt/global-rag/backend')

from mineru_client import MinerUClient, MinerUConnectionError

client = MinerUClient()

# Test health
try:
    h = client.health()
    print('Health:', h['status'], 'version:', h['version'])
except MinerUConnectionError as e:
    print('MinerU not reachable:', e)
    sys.exit(1)

# Test submit
task = client.submit_task('/home/baimo/services/mineru/input/test.pdf')
print('Submitted task:', task.task_id, 'status:', task.status)

# Test poll
final = client.poll_until_complete(task.task_id, max_seconds=60)
print('Final status:', final.status, 'error:', final.error)

# Test fetch
result = client.get_task_result(task.task_id)
print('MD length:', len(result.md_content))
print('Backend:', result.backend)
print('Version:', result.version)
print()
print('=== MINERU CLIENT INTEGRATION TEST PASSED ===')
