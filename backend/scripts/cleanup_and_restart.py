#!/usr/bin/env python3
"""
cleanup_and_restart.py — 全局恢复脚本
======================================
固化到项目目录：backend/scripts/cleanup_and_restart.py

用途：
  1. 清理残留僵尸进程（multiprocessing-spawn）
  2. 停止旧服务（embedding、worker、gateway、mcp）
  3. 重启嵌入服务
  4. 重启 Worker
  5. 重置失败/卡住的作业到 queued
  6. 重启监控脚本

用法：
  cd /opt/global-rag && source venv/bin/activate
  python3 cleanup_and_restart.py
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

VERSION = "1.0"
DB = "/opt/global-rag/data/knowledge-control.db"
LOG_DIR = "/opt/global-rag/logs"
RUN_DIR = "/opt/global-rag/run"
VENV_PYTHON = "/opt/global-rag/venv/bin/python3"


def log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


# ---------------------------------------------------------------------------
# Step 1: Kill orphaned multiprocessing zombie processes
# ---------------------------------------------------------------------------
def cleanup_zombies() -> int:
    """Kill leftover multiprocessing.spawn processes. Returns count killed."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "multiprocessing.spawn"],
            timeout=5, stderr=subprocess.DEVNULL,
        )
        pids = [int(p) for p in out.decode().strip().splitlines() if p.strip()]
        if pids:
            subprocess.run(["kill", "-9"] + [str(p) for p in pids],
                           timeout=5, capture_output=True)
            log(f"  Killed {len(pids)} zombie processes (freed ~{len(pids)*500} MB RAM)")
            return len(pids)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            FileNotFoundError, ValueError):
        pass
    return 0


# ---------------------------------------------------------------------------
# Step 2: Stop all services
# ---------------------------------------------------------------------------
def stop_services() -> None:
    for pattern in ["[e]mbedding_service.py", "[r]ag_gateway.py",
                    "[i]ngest_worker.py", "[r]ag_mcp_server.py"]:
        subprocess.run(["pkill", "-TERM", "-f", pattern],
                       timeout=10, capture_output=True)
    time.sleep(2)
    # Force kill remaining
    for pattern in ["[e]mbedding_service.py", "[r]ag_gateway.py",
                    "[i]ngest_worker.py", "[r]ag_mcp_server.py"]:
        subprocess.run(["pkill", "-9", "-f", pattern],
                       timeout=10, capture_output=True)
    time.sleep(1)
    log("  All services stopped")


# ---------------------------------------------------------------------------
# Step 3: Reset DB — mark stale/failed jobs as queued
# ---------------------------------------------------------------------------
def reset_jobs() -> int:
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, state FROM ingest_jobs WHERE state IN ('running','failed')")
    jobs = c.fetchall()
    for jid, state in jobs:
        c.execute("DELETE FROM parse_jobs WHERE ingest_job_id = ?", (jid,))
        c.execute(
            "UPDATE ingest_jobs SET state='queued', retry_count=0, "
            "error='', worker_id='', lease_until='', progress=0 WHERE id=?",
            (jid,),
        )
    conn.commit()
    conn.close()
    if jobs:
        log(f"  Reset {len(jobs)} stale jobs to queued")
    return len(jobs)


# ---------------------------------------------------------------------------
# Step 4: Start embedding service
# ---------------------------------------------------------------------------
def start_embedding(timeout: int = 120) -> bool:
    log("  Starting embedding service...")
    proc = subprocess.Popen(
        [VENV_PYTHON, "/opt/global-rag/embedding_service.py"],
        stdout=open(f"{LOG_DIR}/embedding-service.log", "a"),
        stderr=subprocess.STDOUT,
        cwd="/opt/global-rag",
    )
    with open(f"{RUN_DIR}/embedding-service.pid", "w") as f:
        f.write(str(proc.pid))

    # Wait for health
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = urllib.request.urlopen("http://127.0.0.1:9102/health", timeout=3)
            data = json.loads(r.read())
            if "loaded" in data.get("model", ""):
                elapsed = int(time.monotonic() - deadline + timeout)
                log(f"  Embedding model ready at {elapsed}s")
                return True
        except Exception:
            pass
        time.sleep(2)
    log(f"  [WARN] Embedding not ready within {timeout}s")
    return False


# ---------------------------------------------------------------------------
# Step 5: Start worker
# ---------------------------------------------------------------------------
def start_worker() -> bool:
    log("  Starting worker...")
    env = os.environ.copy()
    env.update({
        "RAG_INGEST_ROOTS": "/mnt/e/RAG",
        "RAG_AUTO_SCAN_SECONDS": "300",
        "RAG_FILE_STABILITY_SECONDS": "30",
        "RAG_PDF_RENAME_MAX_TOKENS": "2500",
        "RAG_EMBEDDING_CLIENT_TIMEOUT": "300",
    })
    proc = subprocess.Popen(
        [VENV_PYTHON, "/opt/global-rag/ingest_worker.py"],
        stdout=open(f"{LOG_DIR}/ingest_worker.log", "a"),
        stderr=subprocess.STDOUT,
        cwd="/opt/global-rag",
        env=env,
    )
    with open(f"{RUN_DIR}/ingest-worker.pid", "w") as f:
        f.write(str(proc.pid))
    time.sleep(2)
    alive = proc.poll() is None
    log(f"  Worker PID={proc.pid} {'alive' if alive else 'FAILED'}")
    return alive


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log(f"=== cleanup_and_restart.py v{VERSION} ===")
    log("")
    log("Step 1: Clean zombie processes...")
    n = cleanup_zombies()
    log("")
    log("Step 2: Stop old services...")
    stop_services()
    log("")
    log("Step 3: Reset failed/stale jobs...")
    m = reset_jobs()
    log("")
    log("Step 4: Start embedding service...")
    start_embedding()
    log("")
    log("Step 5: Start worker...")
    start_worker()
    log("")
    log("Step 6: Summary")
    log(f"  Zombies cleaned: {n}")
    log(f"  Jobs reset: {m}")
    log("")
    log("=== Done ===")


if __name__ == "__main__":
    main()
