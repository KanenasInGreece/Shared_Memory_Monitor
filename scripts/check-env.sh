#!/usr/bin/env bash
# Validate this monitor's gateway wiring. Prints no secrets.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python -m sm_telemetry_monitor check "$@"