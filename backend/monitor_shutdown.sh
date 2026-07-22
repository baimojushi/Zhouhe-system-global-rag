#!/bin/bash
# Monitor MinerU, run final test, then shutdown
while true; do
  h=$(curl -sS http://127.0.0.1:18000/health 2>/dev/null)
  c=$(echo "$h" | grep -oP '"completed_tasks":\K[0-9]+')
  echo "$(date +%H:%M:%S) completed=$c" >> /home/baimo/services/mineru/logs/monitor.log
  if [ "$c" -ge 6 ]; then
    echo "=== MONOGRAPH DONE ===" >> /home/baimo/services/mineru/logs/monitor.log
    cd /opt/global-rag/backend
    source ~/services/mineru/venv/bin/activate
    cp /mnt/d/ai/qwen-code/bin/global-rag-system/backend/test_monograph_final.py /tmp/
    python3 /tmp/test_monograph_final.py >> /home/baimo/services/mineru/logs/monograph_test.log 2>&1
    echo "=== TEST DONE ===" >> /home/baimo/services/mineru/logs/monitor.log
    sudo shutdown -h now
    break
  fi
  sleep 60
done
