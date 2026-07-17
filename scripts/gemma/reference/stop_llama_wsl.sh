#!/bin/bash
# 停止所有 llama-server / llama-bench 进程

pids=$(ps -eo pid --no-headers | grep -E 'llama-server|llama-bench' | grep -v grep | awk '{print $1}')

if [ -z "$pids" ]; then
  echo "  没有 llama-server / llama-bench 进程在运行"
else
  for pid in $pids; do
    echo "  终止 PID $pid"
    kill -9 "$pid" 2>/dev/null || true
  done
fi