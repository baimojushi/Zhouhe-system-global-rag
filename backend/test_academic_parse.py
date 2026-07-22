#!/usr/bin/env python3
"""Run academic PDF through MinerU and save structured output."""
import sys, json
sys.path.insert(0, '/opt/global-rag/backend')
from mineru_client import MinerUClient

client = MinerUClient()
task = client.submit_task(
    '/home/baimo/services/mineru/input/test_academic.pdf',
    return_md=True,
    return_content_list=True,
    return_middle_json=True,
)
print('Task:', task.task_id)
final = client.poll_until_complete(task.task_id, max_seconds=300)
print('Status:', final.status)
result = client.get_task_result(task.task_id)
print('MD length:', len(result.md_content))
print('Content list entries:', len(result.content_list))

with open('/home/baimo/services/mineru/output/academic_content_list.json', 'w') as f:
    json.dump(result.content_list, f, ensure_ascii=False, indent=2)
with open('/home/baimo/services/mineru/output/academic_md.md', 'w') as f:
    f.write(result.md_content)
print('Saved to /home/baimo/services/mineru/output/')
