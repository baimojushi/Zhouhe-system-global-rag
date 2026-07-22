#!/usr/bin/env python3
"""Parse monograph PDF through MinerU and save all outputs."""
import sys, json
sys.path.insert(0, '/opt/global-rag/backend')
from mineru_client import MinerUClient

client = MinerUClient()
print('Submitting monograph (15MB)...')
task = client.submit_task(
    '/home/baimo/services/mineru/input/monograph.pdf',
    return_md=True,
    return_content_list=True,
    return_middle_json=True,
)
print('Task:', task.task_id)

print('Polling (timeout=600s)...')
final = client.poll_until_complete(task.task_id, max_seconds=600)
print('Status:', final.status, 'error:', final.error)

print('Fetching result...')
result = client.get_task_result(task.task_id)
print('MD length:', len(result.md_content))
print('Content list entries:', len(result.content_list))

# Save outputs
with open('/home/baimo/services/mineru/output/monograph_md.md', 'w') as f:
    f.write(result.md_content)
with open('/home/baimo/services/mineru/output/monograph_content_list.json', 'w') as f:
    json.dump(result.content_list, f, ensure_ascii=False, indent=2)
print('Saved to /home/baimo/services/mineru/output/')

# Quick stats
import re
pages = len(re.findall(r'\n\n\n\n', result.md_content)) + 1
print(f'Estimated pages: {pages}')
print(f'Characters: {len(result.md_content)}')
