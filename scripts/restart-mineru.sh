#!/bin/bash
set -euo pipefail

echo "=== Restart MinerU ==="

echo "  Cleaning stale loky temp dirs..."
rm -rf /tmp/loky-*

# Kill old
pkill -TERM -f 'mineru-api' 2>/dev/null || true
sleep 2
pkill -9 -f 'mineru-api' 2>/dev/null || true
pkill -9 -f 'loky' 2>/dev/null || true
sleep 2

echo "  Old MinerU killed, starting fresh..."

# Start fresh
cd /home/baimo/services/mineru
source venv/bin/activate

export MINERU_MODEL_SOURCE=local
export CUDA_VISIBLE_DEVICES=1
export MINERU_API_OUTPUT_ROOT=/home/baimo/services/mineru/output
export MINERU_API_MAX_CONCURRENT_REQUESTS=1
export MINERU_PROCESSING_WINDOW_SIZE=16
export MINERU_PDF_RENDER_THREADS=8
export MINERU_INTRA_OP_NUM_THREADS=12
export MINERU_INTER_OP_NUM_THREADS=2
export MINERU_HYBRID_BATCH_RATIO=4
export MINERU_API_TASK_RETENTION_SECONDS=86400
export MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS=300
export MINERU_API_ENABLE_FASTAPI_DOCS=true

nohup mineru-api \
  --host 127.0.0.1 \
  --port 18000 \
  --gpu-memory-utilization 0.40 \
  --enable-vlm-preload false \
  > /opt/global-rag/logs/mineru.log 2>&1 &
MINERU_PID=$!
echo "  New MinerU PID=$MINERU_PID"

# Wait for health
for i in $(seq 1 30); do
  if curl -s -m 3 http://127.0.0.1:18000/health >/dev/null 2>&1; then
    echo "  Ready at ${i}s"
    break
  fi
  sleep 2
done

# Also restart worker so it resubmits
echo "  Restarting worker in tmux..."
pkill -TERM -f '[i]ngest_worker.py' 2>/dev/null || true
sleep 1
tmux kill-session -t worker 2>/dev/null
cd /opt/global-rag
RAG_INGEST_ROOTS=/mnt/e/RAG tmux new-session -d -s worker "venv/bin/python3 ingest_worker.py"
echo "  Worker started in tmux session 'worker'"

echo ""
echo "=== Done ==="
