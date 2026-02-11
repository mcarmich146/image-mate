#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:app --reload --host "${IMAGE_MATE_HOST:-0.0.0.0}" --port "${IMAGE_MATE_PORT:-8000}"
