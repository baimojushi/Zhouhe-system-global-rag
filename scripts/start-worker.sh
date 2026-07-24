#!/bin/bash
# 启动 Worker（tmux 持久会话）
cd /opt/global-rag
export RAG_INGEST_ROOTS=/mnt/e/RAG
export RAG_MINERU_SUBMIT_TIMEOUT_SECONDS=300
tmux kill-session -t worker 2>/dev/null
tmux new-session -d -s worker "venv/bin/python3 ingest_worker.py"
echo "Worker started in tmux session 'worker'"
