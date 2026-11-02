#!/usr/bin/env bash
# Serve the loopback dashboard without starting the poll loop.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python -m sm_telemetry_monitor serve
