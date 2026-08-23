#!/usr/bin/env bash
# Validate monitor wiring to a shared-memory framework checkout (no secrets printed).
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python -m sm_telemetry_monitor check "$@"