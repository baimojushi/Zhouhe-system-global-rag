#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ACTION="${1:-}"
PROFILE="${2:-}"

usage() {
  echo "Usage: $0 {run|stop|status} {q4|q8|all}" >&2
  exit 64
}

[[ "$ACTION" =~ ^(run|stop|status)$ ]] || usage
[[ "$PROFILE" =~ ^(q4|q8|all)$ ]] || usage
[[ "$ACTION" != "run" || "$PROFILE" != "all" ]] || usage

BINARY="${LLAMA_SERVER_BINARY:-/home/llama.cpp/build/bin/llama-server}"
STATE_DIR="${LLAMA_STATE_DIR:-${HOME}/.local/state/global-rag-llama}"
LOG_DIR="${LLAMA_LOG_DIR:-${HOME}/.local/state/global-rag-llama/logs}"
mkdir -p "$STATE_DIR" "$LOG_DIR"

load_profile() {
  local profile="$1"
  case "$profile" in
    q4)
      NAME="llama_q4"
      PORT="${LLAMA_Q4_PORT:-8000}"
      MODEL="${LLAMA_Q4_MODEL:-${HOME}/models/gemma4-crack-Q4_K_M/gemma-4-31b-jang-crack-Q4_K_M.gguf}"
      LAST_SHARD=""
      ALIAS="${LLAMA_Q4_ALIAS:-gemma-4-31b-q4}"
      ARGS=(--device CUDA0,CUDA1 --split-mode layer --tensor-split 1,1 --n-gpu-layers all --flash-attn on --ctx-size 16384 --parallel 2 --batch-size 2048 --ubatch-size 512 --cache-type-k q8_0 --cache-type-v q8_0)
      ;;
    q8)
      NAME="llama_q8"
      PORT="${LLAMA_Q8_PORT:-8002}"
      MODEL="${LLAMA_Q8_MODEL:-${HOME}/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00001-of-00009.gguf}"
      LAST_SHARD="${LLAMA_Q8_LAST_SHARD:-${HOME}/models/gemma4-crack-Q8_0/gemma-4-31b-jang-crack-Q8_0-00009-of-00009.gguf}"
      ALIAS="${LLAMA_Q8_ALIAS:-gemma-4-31b-q8}"
      ARGS=(--fit off --split-mode layer --tensor-split 1,1 --n-gpu-layers 58 --ctx-size 4096 --parallel 1 --batch-size 256 --ubatch-size 128 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on --log-verbosity 2)
      ;;
  esac
  WRAPPER_PID_FILE="${STATE_DIR}/${NAME}.wrapper.pid"
  SERVER_PID_FILE="${STATE_DIR}/${NAME}.server.pid"
  LOCK_FILE="${STATE_DIR}/${NAME}.lock"
  LOG_FILE="${LOG_DIR}/${NAME}.log"
}

valid_pid() {
  local pid="${1:-}" marker="${2:-}"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  tr '\0' ' ' < "/proc/${pid}/cmdline" | grep -Fq -- "$marker"
}

valid_server_pid() {
  local pid="${1:-}"
  valid_pid "$pid" "--port ${PORT}" && valid_pid "$pid" "$MODEL"
}

find_server_pid() {
  local proc pid cmd
  for proc in /proc/[0-9]*; do
    [[ -r "$proc/cmdline" ]] || continue
    pid="${proc##*/}"
    cmd="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
    [[ "$cmd" == *"$BINARY"* && "$cmd" == *"$MODEL"* && "$cmd" == *"--port ${PORT}"* ]] || continue
    echo "$pid"
    return 0
  done
  return 1
}

stop_profile() {
  local profile="$1" pid="" elapsed=0 wrapper_signaled=0
  load_profile "$profile"

  if [[ -s "$WRAPPER_PID_FILE" ]]; then
    pid="$(cat "$WRAPPER_PID_FILE" 2>/dev/null || true)"
    if valid_pid "$pid" "llama-service.sh run ${profile}"; then
      echo "Stopping ${NAME} wrapper pid=${pid}"
      kill -TERM "$pid" 2>/dev/null || true
      wrapper_signaled=1
    fi
  fi

  while (( wrapper_signaled == 1 && elapsed < 20 )); do
    pid="$(cat "$SERVER_PID_FILE" 2>/dev/null || true)"
    if ! valid_server_pid "$pid"; then break; fi
    sleep 1
    ((elapsed+=1))
  done

  pid="$(cat "$SERVER_PID_FILE" 2>/dev/null || true)"
  if ! valid_server_pid "$pid"; then pid="$(find_server_pid || true)"; fi
  if valid_server_pid "$pid"; then
    echo "Stopping ${NAME} server pid=${pid}"
    kill -TERM "$pid" 2>/dev/null || true
    sleep 3
  fi
  if valid_server_pid "$pid"; then
    echo "Force stopping verified ${NAME} server pid=${pid}"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$WRAPPER_PID_FILE" "$SERVER_PID_FILE"
}

status_profile() {
  local profile="$1" pid=""
  load_profile "$profile"
  pid="$(cat "$SERVER_PID_FILE" 2>/dev/null || true)"
  if ! valid_server_pid "$pid"; then pid="$(find_server_pid || true)"; fi
  if valid_server_pid "$pid" && curl -fsS -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "${NAME}: online pid=${pid} port=${PORT}"
    return 0
  fi
  echo "${NAME}: offline port=${PORT}"
  return 1
}

run_profile() {
  local profile="$1" child_pid="" existing_pid=""
  load_profile "$profile"

  [[ -x "$BINARY" ]] || { echo "[FATAL] llama-server not executable: $BINARY" >&2; exit 126; }
  [[ -s "$MODEL" ]] || { echo "[FATAL] model missing or empty: $MODEL" >&2; exit 2; }
  [[ -z "$LAST_SHARD" || -s "$LAST_SHARD" ]] || { echo "[FATAL] last model shard missing or empty: $LAST_SHARD" >&2; exit 2; }

  existing_pid="$(find_server_pid || true)"
  [[ -z "$existing_pid" ]] || { echo "[FATAL] ${NAME} server already exists: pid=${existing_pid}" >&2; exit 17; }

  exec 9>"$LOCK_FILE"
  flock -n 9 || { echo "[FATAL] ${NAME} wrapper already owns the service lock" >&2; exit 17; }

  echo "$$" > "$WRAPPER_PID_FILE"
  : > "$LOG_FILE"
  exec >>"$LOG_FILE" 2>&1
  echo "[$(date -Is)] starting ${NAME}; wrapper_pid=$$; port=${PORT}; model=${MODEL}"

  cleanup() {
    local status=$?
    rm -f "$WRAPPER_PID_FILE" "$SERVER_PID_FILE"
    echo "[$(date -Is)] ${NAME} wrapper exiting status=${status}"
  }
  forward() {
    if [[ -n "${child_pid:-}" ]] && valid_server_pid "$child_pid"; then
      kill -TERM "$child_pid" 2>/dev/null || true
    fi
  }
  trap forward TERM INT HUP
  trap cleanup EXIT

  export CUDA_DEVICE_ORDER=PCI_BUS_ID
  export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
  "$BINARY" --model "$MODEL" --alias "$ALIAS" "${ARGS[@]}" --host 0.0.0.0 --port "$PORT" &
  child_pid=$!
  echo "$child_pid" > "$SERVER_PID_FILE"
  echo "[$(date -Is)] llama-server pid=${child_pid}"
  wait "$child_pid"
}

case "$ACTION:$PROFILE" in
  run:q4|run:q8) run_profile "$PROFILE" ;;
  stop:all) stop_profile q4; stop_profile q8 ;;
  stop:q4|stop:q8) stop_profile "$PROFILE" ;;
  status:all)
    result=0
    status_profile q4 || result=1
    status_profile q8 || result=1
    exit "$result"
    ;;
  status:q4|status:q8) status_profile "$PROFILE" ;;
  *) usage ;;
esac
