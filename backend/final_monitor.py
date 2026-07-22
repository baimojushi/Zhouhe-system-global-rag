#!/usr/bin/env python3
"""Wait for monograph output, run final test, then shutdown."""
import time, os, subprocess, json

OUT_MD = '/home/baimo/services/mineru/output/monograph_md.md'
OUT_CL = '/home/baimo/services/mineru/output/monograph_content_list.json'
TEST_LOG = '/home/baimo/services/mineru/logs/monograph_test.log'
MONITOR_LOG = '/home/baimo/services/mineru/logs/monitor.log'

def log(msg):
    with open(MONITOR_LOG, 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')

log('Final monitor started, waiting for monograph output...')

# Wait for output files (up to 3 hours)
deadline = time.time() + 10800  # 3 hours
while time.time() < deadline:
    if os.path.exists(OUT_MD) and os.path.getsize(OUT_MD) > 0:
        size = os.path.getsize(OUT_MD)
        log(f'Output file found: {size} bytes')
        break
    time.sleep(30)
else:
    log('TIMEOUT waiting for monograph output')
    subprocess.run(['sudo', 'shutdown', '-h', 'now'], timeout=30)
    sys.exit(1)

# Run final test
log('Running final test...')
result = subprocess.run(
    ['bash', '-c', 
     f'cd /opt/global-rag/backend && source ~/services/mineru/venv/bin/activate && '
     f'cp /mnt/d/ai/qwen-code/bin/global-rag-system/backend/test_monograph_final.py /tmp/ && '
     f'python3 /tmp/test_monograph_final.py'],
    capture_output=True, text=True, timeout=300
)

with open(TEST_LOG, 'w') as f:
    f.write(result.stdout)
    f.write('\n---STDERR---\n')
    f.write(result.stderr)
    f.write(f'\n---RC={result.returncode}---\n')

if result.returncode == 0:
    log('=== TEST PASSED ===')
else:
    log('=== TEST FAILED ===')
    log(f'stdout: {result.stdout[-500:]}')
    log(f'stderr: {result.stderr[-500:]}')

# Shutdown regardless
log('Shutting down...')
subprocess.run(['sudo', 'shutdown', '-h', 'now'], timeout=30)
