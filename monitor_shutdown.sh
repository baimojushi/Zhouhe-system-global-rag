#!/bin/bash
# MinerU 空闲监控 — 任务完成后自动关机
# 部署到项目: D:\ai\qwen-code\bin\global-rag-system\monitor_shutdown.sh
# 用法: WSL 侧 bash ~/monitor_shutdown.sh &
#
# 检测条件（全部满足连续 4 次）：
#   1. MinerU 无处理中/排队任务
#   2. Worker 任务队列为空（DB 中无 running/queued job）
#   3. Embedding 服务无积压（queue_high_depth=0 且 queue_low_depth=0）

POLL_SECONDS=30
IDLE_ROUNDS=4   # 连续 4 次空闲（~2 分钟）后关机

echo "[$(date '+%H:%M:%S')] MinerU 空闲监控启动"
echo "  检查间隔: ${POLL_SECONDS}s"
echo "  空闲确认: 连续 ${IDLE_ROUNDS} 次后关机"
echo ""

idle_count=0

while true; do
  now=$(date '+%H:%M:%S')

  # 1. MinerU 状态
  h=$(curl -s -m 5 http://127.0.0.1:18000/health 2>/dev/null)
  p=$(echo "$h" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('processing_tasks',1))" 2>/dev/null || echo 1)
  q=$(echo "$h" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('queued_tasks',1))" 2>/dev/null || echo 1)
  c=$(echo "$h" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('completed_tasks',1))" 2>/dev/null || echo 0)

  # 2. DB 待处理任务
  db=$(source /opt/global-rag/venv/bin/activate 2>/dev/null && python3 -c "
import sqlite3
conn=sqlite3.connect('/opt/global-rag/data/knowledge-control.db')
c=conn.cursor()
c.execute(\"SELECT COUNT(*) FROM ingest_jobs WHERE state IN ('running','queued')\")
print(c.fetchone()[0])
" 2>/dev/null || echo 1)

  # 3. Embedding 队列积压（queue depth > 0 表示有未完成的编码任务）
  em=$(curl -s -m 3 http://127.0.0.1:9102/metrics 2>/dev/null | \
    python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('queue_high_depth',1)+d.get('queue_low_depth',1))" 2>/dev/null || echo 1)

  # 判断是否空闲（Worker 存活不影响判断——它是常驻进程）
  if [ "$p" = "0" ] && [ "$q" = "0" ] && [ "$db" = "0" ] && [ "$em" = "0" ]; then
    idle_count=$((idle_count + 1))
    echo "[$now] 空闲确认 ${idle_count}/${IDLE_ROUNDS}（MinerU=${p}/${q} DB=${db} Embed=${em} 已完成=${c}）"
  else
    idle_count=0
    echo "[$now] 运行中（MinerU=${p}/${q} DB=${db} Embed=${em} 已完成=${c}）"
  fi

  if [ "$idle_count" -ge "$IDLE_ROUNDS" ]; then
    echo ""
    echo "[$now] ============ 所有任务完成（${c} tasks），120 秒后关机 ============"
    cmd.exe /c shutdown /s /t 120
    break
  fi

  sleep "$POLL_SECONDS"
done
