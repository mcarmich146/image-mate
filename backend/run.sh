#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

HOST="${IMAGE_MATE_HOST:-127.0.0.1}"
PORT="${IMAGE_MATE_PORT:-8000}"
LOG_DIR="${IMAGE_MATE_LOG_DIR:-$SCRIPT_DIR/output/logs}"
mkdir -p "$LOG_DIR"

PYTHON_BIN="${IMAGE_MATE_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  printf '%s\n' "[image-mate] no usable Python interpreter found; set IMAGE_MATE_PYTHON" >&2
  exit 127
fi
if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
  printf '%s\n' "[image-mate] Python interpreter cannot import uvicorn: $PYTHON_BIN" >&2
  exit 127
fi

STAMP="$(date -u +"%Y%m%d_%H%M%S")"
RUN_LOG="$LOG_DIR/backend_${STAMP}.log"
LATEST_LOG="$LOG_DIR/backend_latest.log"
ln -sfn "$(basename "$RUN_LOG")" "$LATEST_LOG"

{
  echo "[image-mate] $(date -u +"%Y-%m-%dT%H:%M:%SZ") starting backend host=${HOST} port=${PORT}"
  echo "[image-mate] project directory: $PROJECT_DIR"
  echo "[image-mate] python interpreter: $PYTHON_BIN"
  echo "[image-mate] log file: $RUN_LOG"
  echo "[image-mate] latest log symlink: $LATEST_LOG"
} | tee -a "$RUN_LOG"

set +e
DEV_RELOAD="${IMAGE_MATE_DEV_RELOAD:-false}"
UVICORN_ARGS=( -m uvicorn app.main:app --host "$HOST" --port "$PORT" )
if [[ "$DEV_RELOAD" == "1" || "$DEV_RELOAD" == "true" || "$DEV_RELOAD" == "yes" ]]; then
  UVICORN_ARGS+=(--reload)
fi
"$PYTHON_BIN" "${UVICORN_ARGS[@]}" 2>&1 | tee -a "$RUN_LOG"
STATUS=${PIPESTATUS[0]}
set -e

echo "[image-mate] $(date -u +"%Y-%m-%dT%H:%M:%SZ") backend exited status=${STATUS}" | tee -a "$RUN_LOG"
exit "$STATUS"
