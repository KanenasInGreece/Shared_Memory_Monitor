#!/usr/bin/env bash
# Validate monitor wiring to a shared-memory framework checkout (no secrets printed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python -m sm_telemetry_monitor check "$@"