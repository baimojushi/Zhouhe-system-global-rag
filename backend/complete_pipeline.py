#!/usr/bin/env python3
"""Complete the monograph test pipeline: submit, wait, fetch, test, shutdown."""
import sys, json, time, os, subprocess, urllib.request, urllib.error

API = 'http://127.0.0.1:18000'
OUT = '/home/baimo/services/mineru/output'
MONITOR_LOG = '/home/baimo/services/mineru/logs/monitor.log'

def log(msg):
    with open(MONITOR_LOG, 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')

def api_get(path):
    try:
        return json.loads(urllib.request.urlopen(f'{API}{path}', timeout=10).read())
    except Exception as e:
        log(f'API error: {e}')
        return None

def submit_and_wait():
    """Submit monograph and wait for completion. Returns task_id."""
    import http.client
    import io

    boundary = '----Boundary7MA4YWxkTrZu0gW'
    filepath = '/home/baimo/services/mineru/input/monograph.pdf'
    
    with open(filepath, 'rb') as f:
        file_data = f.read()
    
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="files"; filename="monograph.pdf"\r\n'
        f'Content-Type: application/pdf\r\n\r\n'
    ).encode() + file_data + (
        f'\r\n--{boundary}\r\n'
        f'Content-Disposition: form-data; name="return_md"\r\n\r\ntrue\r\n'
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="return_content_list"\r\n\r\ntrue\r\n'
        f'--{boundary}--\r\n'
    ).encode()
    
    req = urllib.request.Request(
        f'{API}/tasks',
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
    )
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        task_id = data.get('task_id', '')
        log(f'Submitted task: {task_id}')
    except Exception as e:
        log(f'Submit failed: {e}')
        return None
    
    # Poll until complete
    log('Waiting for completion...')
    deadline = time.time() + 7200  # 2 hours
    while time.time() < deadline:
        h = api_get('/health')
        if h:
            c = h.get('completed_tasks', 0)
            q = h.get('queued_tasks', 0)
            p = h.get('processing_tasks', 0)
            log(f'q={q} p={p} c={c}')
            if c >= 1 and q == 0 and p == 0:
                log('Task completed!')
                return task_id
        time.sleep(30)
    
    log('TIMEOUT waiting for completion')
    return None

def fetch_and_test(task_id):
    """Fetch result, save outputs, run test."""
    # Fetch result
    try:
        resp = urllib.request.urlopen(f'{API}/tasks/{task_id}/result', timeout=30)
        result = json.loads(resp.read())
    except Exception as e:
        log(f'Fetch failed: {e}')
        return False
    
    # Extract per-file results
    results = result.get('results', {})
    for fname, fresult in results.items():
        if isinstance(fresult, dict):
            md = fresult.get('md_content', '')
            cl = fresult.get('content_list', [])
            
            with open(f'{OUT}/monograph_md.md', 'w') as f:
                f.write(md)
            with open(f'{OUT}/monograph_content_list.json', 'w') as f:
                json.dump(cl, f, ensure_ascii=False, indent=2)
            
            log(f'Saved: MD={len(md)} chars, CL={len(cl)} entries')
            break
    
    # Run test
    log('Running final test...')
    test_script = '/mnt/d/ai/qwen-code/bin/global-rag-system/backend/test_monograph_final.py'
    result = subprocess.run(
        ['bash', '-c',
         f'cd /opt/global-rag/backend && source ~/services/mineru/venv/bin/activate && '
         f'cp {test_script} /tmp/ && python3 /tmp/test_monograph_final.py'],
        capture_output=True, text=True, timeout=300
    )
    
    test_log = f'{OUT}/../logs/monograph_test.log'
    with open(test_log, 'w') as f:
        f.write(result.stdout)
        f.write(f'\n---RC={result.returncode}---\n')
        f.write(result.stderr)
    
    if result.returncode == 0:
        log('=== TEST PASSED ===')
        return True
    else:
        log(f'=== TEST FAILED (rc={result.returncode}) ===')
        log(f'stderr: {result.stderr[-300:]}')
        return False

# Main
log('=== COMPLETE PIPELINE STARTED ===')
task_id = submit_and_wait()
if task_id:
    if fetch_and_test(task_id):
        log('Shutting down...')
        subprocess.run(['sudo', 'shutdown', '-h', 'now'], timeout=30)
    else:
        log('Test failed, not shutting down')
else:
    log('Pipeline failed')
