#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

NAME="llama_q4"
BINARY="/home/llama.cpp/build/bin/llama-server"
MODEL="/home/baimo/models/gemma4-crack-Q4_K_M/gemma-4-31b-jang-crack-Q4_K_M.gguf"
STATE_DIR="/home/baimo/.local/state/llama"
LOG_FILE="/home/baimo/q4-server.log"
WRAPPER_PID_FILE="${STATE_DIR}/${NAME}.wrapper.pid"
SERVER_PID_FILE="${STATE_DIR}/${NAME}.server.pid"

mkdir -p "$STATE_DIR"
: > "$LOG_FILE"
exec >>"$LOG_FILE" 2>&1

echo "[$(date -Is)] starting ${NAME}"
echo "wrapper_pid=$$"
echo "user=$(id -un)"
echo "model=${MODEL}"

if [[ ! -x "$BINARY" ]]; then
    echo "[FATAL] llama-server not executable: $BINARY"
    exit 126
fi
if [[ ! -s "$MODEL" ]]; then
    echo "[FATAL] model missing or empty: $MODEL"
    exit 2
fi

if [[ -s "$WRAPPER_PID_FILE" ]]; then
    old_pid="$(cat "$WRAPPER_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
        echo "[FATAL] another wrapper is already running: pid=$old_pid"
        exit 17
    fi
fi

echo "$$" > "$WRAPPER_PID_FILE"
child_pid=""

forward_signal() {
    local signal="${1:-TERM}"
    if [[ -n "${child_pid:-}" ]] && kill -0 "$child_pid" 2>/dev/null; then
        echo "[$(date -Is)] forwarding ${signal} to llama-server pid=${child_pid}"
        kill "-${signal}" "$child_pid" 2>/dev/null || true
    fi
}

cleanup() {
    local status=$?
    rm -f "$WRAPPER_PID_FILE" "$SERVER_PID_FILE"
    echo "[$(date -Is)] ${NAME} wrapper exiting status=${status}"
}

trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT
trap 'forward_signal HUP' HUP
trap cleanup EXIT

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0,1

"$BINARY" \
  --model "$MODEL" \
  --device CUDA0,CUDA1 \
  --split-mode layer \
  --tensor-split 1,1 \
  --n-gpu-layers all \
  --flash-attn on \
  --ctx-size 16384 \
  --parallel 2 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --host 0.0.0.0 \
  --port 8000 &

child_pid=$!
echo "$child_pid" > "$SERVER_PID_FILE"
echo "[$(date -Is)] llama-server pid=${child_pid}"

set +e
wait "$child_pid"
status=$?
set -e
echo "[$(date -Is)] llama-server exited status=${status}"
exit "$status"
