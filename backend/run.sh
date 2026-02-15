#!/usr/bin/env bash
set -euo pipefail

HOST="${IMAGE_MATE_HOST:-0.0.0.0}"
PORT="${IMAGE_MATE_PORT:-8000}"
LOG_DIR="${IMAGE_MATE_LOG_DIR:-$(pwd)/output/logs}"
mkdir -p "$LOG_DIR"

STAMP="$(date -u +"%Y%m%d_%H%M%S")"
RUN_LOG="$LOG_DIR/backend_${STAMP}.log"
LATEST_LOG="$LOG_DIR/backend_latest.log"
ln -sfn "$(basename "$RUN_LOG")" "$LATEST_LOG"

{
  echo "[image-mate] $(date -u +"%Y-%m-%dT%H:%M:%SZ") starting backend host=${HOST} port=${PORT}"
  echo "[image-mate] log file: $RUN_LOG"
  echo "[image-mate] latest log symlink: $LATEST_LOG"
} | tee -a "$RUN_LOG"

set +e
uvicorn app.main:app --reload --host "$HOST" --port "$PORT" 2>&1 | tee -a "$RUN_LOG"
STATUS=${PIPESTATUS[0]}
set -e

echo "[image-mate] $(date -u +"%Y-%m-%dT%H:%M:%SZ") backend exited status=${STATUS}" | tee -a "$RUN_LOG"
exit "$STATUS"
