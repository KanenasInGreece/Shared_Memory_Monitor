#!/usr/bin/env bash
# Capture README screenshots from a running monitor (http://127.0.0.1:8765).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv &>/dev/null; then
  echo "uv is required to run capture_screenshots.py" >&2
  exit 1
fi

# One-time browser fetch; safe to re-run (no-op when already installed).
uv run --with playwright playwright install chromium >/dev/null 2>&1 || true

exec uv run --with playwright python "$ROOT/scripts/capture_screenshots.py"