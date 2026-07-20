#!/bin/bash
cd /opt/global-rag
source venv/bin/activate
export RAG_INGEST_ROOTS=/mnt/e/RAG
export RAG_AUTO_SCAN_SECONDS=300
export RAG_FILE_STABILITY_SECONDS=30
mkdir -p "/mnt/e/RAG/AI工作记录" "/mnt/e/RAG/学术资料" "/mnt/e/RAG/生产文档" "/mnt/e/RAG/个人思维笔记"
python3 ingest_worker.py &
worker_pid=$!
trap 'kill -TERM "$worker_pid" 2>/dev/null || true' EXIT INT TERM
python3 rag_gateway.py --port 9100
