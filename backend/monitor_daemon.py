#!/usr/bin/env python3
"""Monitor MinerU, run final test, then shutdown."""
import subprocess, time, json, os, sys

LOG = '/home/baimo/services/mineru/logs/monitor.log'
TEST_SCRIPT = '/mnt/d/ai/qwen-code/bin/global-rag-system/backend/test_monograph_final.py'

def log(msg):
    with open(LOG, 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')

def check_completed():
    try:
        import urllib.request
        resp = urllib.request.urlopen('http://127.0.0.1:18000/health', timeout=10)
        data = json.loads(resp.read())
        return data.get('completed_tasks', 0)
    except Exception as e:
        log(f'Health check failed: {e}')
        return None

def run_test():
    log('Running final test...')
    result = subprocess.run(
        ['bash', '-c', f'cd /opt/global-rag/backend && source ~/services/mineru/venv/bin/activate && python3 {TEST_SCRIPT}'],
        capture_output=True, text=True, timeout=300
    )
    log(f'Test stdout: {result.stdout[-500:]}')
    log(f'Test stderr: {result.stderr[-500:]}')
    log(f'Test return code: {result.returncode}')
    return result.returncode == 0

def shutdown():
    log('Shutting down...')
    subprocess.run(['sudo', 'shutdown', '-h', 'now'], timeout=30)

log('Monitor started')
while True:
    c = check_completed()
    if c is not None:
        log(f'completed_tasks={c}')
        if c >= 6:
            log('Monograph parsed!')
            if run_test():
                log('=== TEST PASSED ===')
                shutdown()
                break
            else:
                log('=== TEST FAILED ===')
                break
    time.sleep(60)
