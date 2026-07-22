#!/usr/bin/env python3
"""Fetch monograph result and run final test."""
import sys, json, os, time
sys.path.insert(0, '/opt/global-rag/backend')
from mineru_client import MinerUClient

c = MinerUClient()

# The last completed task should be the monograph
# Let's check how many tasks there are and get the latest
h = c.health()
print(f'Completed tasks: {h.get("completed_tasks")}')

# We need to find the monograph task. Since we don't have a task list API,
# let's submit a quick task and check what's pending
# Actually, let me just check the status of known task IDs from earlier runs
# The last task we submitted was in check_monograph.py but it timed out

# Strategy: try to get the output from the last completed task
# MinerU stores results for completed tasks - we can access by task_id
# Let me check if the monograph.md was already created by checking the API

# Try to get task result - we need the task_id from the earlier submission
# The task was submitted in check_monograph.py which timed out
# Let me check if there's a way to find the task

# Actually, let me just re-submit with a new parse and wait
print('Re-submitting monograph for parsing (will use cache)...')
task = c.submit_task(
    '/home/baimo/services/mineru/input/monograph.pdf',
    return_md=True,
    return_content_list=True,
)
print(f'Task: {task.task_id}')

# Poll
deadline = time.time() + 600
while time.time() < deadline:
    status = c.get_task_status(task.task_id)
    print(f'  Status: {status.status}')
    if status.is_terminal:
        break
    time.sleep(10)

if status.is_success:
    result = c.get_task_result(task.task_id)
    print(f'MD length: {len(result.md_content)}')
    print(f'Content list: {len(result.content_list)} entries')
    
    # Save
    with open('/home/baimo/services/mineru/output/monograph_md.md', 'w') as f:
        f.write(result.md_content)
    with open('/home/baimo/services/mineru/output/monograph_content_list.json', 'w') as f:
        json.dump(result.content_list, f, ensure_ascii=False, indent=2)
    print('Saved output files')
    
    # Check files exist
    import os.path
    if os.path.exists('/home/baimo/services/mineru/output/monograph_md.md'):
        size = os.path.getsize('/home/baimo/services/mineru/output/monograph_md.md')
        print(f'Output file size: {size} bytes')
else:
    print(f'Failed: {status.error}')
