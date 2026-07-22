#!/usr/bin/env python3
"""Check MinerU task status and retry monograph parse if needed."""
import sys, json, time
sys.path.insert(0, '/opt/global-rag/backend')
from mineru_client import MinerUClient

c = MinerUClient()
h = c.health()
print('Health:', json.dumps(h, indent=2))

# If no monograph output yet, resubmit with longer timeout
import os
if not os.path.exists('/home/baimo/services/mineru/output/monograph_md.md'):
    print('\nMonograph not parsed yet. Submitting...')
    task = c.submit_task(
        '/home/baimo/services/mineru/input/monograph.pdf',
        return_md=True,
        return_content_list=True,
    )
    print('Task:', task.task_id)
    
    # Poll with longer timeout
    deadline = time.time() + 900  # 15 minutes
    while time.time() < deadline:
        status = c.get_task_status(task.task_id)
        print(f'  Status: {status.status} ({time.time():.0f})')
        if status.is_terminal:
            break
        time.sleep(10)
    
    if status.is_success:
        result = c.get_task_result(task.task_id)
        with open('/home/baimo/services/mineru/output/monograph_md.md', 'w') as f:
            f.write(result.md_content)
        with open('/home/baimo/services/mineru/output/monograph_content_list.json', 'w') as f:
            json.dump(result.content_list, f, ensure_ascii=False, indent=2)
        print(f'Saved: MD={len(result.md_content)} chars, CL={len(result.content_list)} entries')
    else:
        print(f'Failed: {status.error}')
else:
    print('\nMonograph already parsed.')
