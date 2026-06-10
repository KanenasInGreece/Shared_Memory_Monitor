#!/usr/bin/env bash
# Capture README screenshots from a running monitor (http://127.0.0.1:8765).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/docs/images"
BASE="${SM_SCREENSHOT_URL:-http://127.0.0.1:8765}"

CHROME="${CHROME:-}"
for candidate in google-chrome chromium chromium-browser; do
  if command -v "$candidate" &>/dev/null; then
    CHROME="$candidate"
    break
  fi
done

if [[ -z "$CHROME" ]]; then
  echo "No headless Chrome found (google-chrome / chromium)." >&2
  exit 1
fi

if ! curl -sf "$BASE/api/meta" -o /dev/null; then
  echo "Monitor not reachable at $BASE — start it first:" >&2
  echo "  ./scripts/run-loop.sh --serve --interval 600" >&2
  exit 1
fi

mkdir -p "$OUT"

shot() {
  local name="$1" path="$2" budget="${3:-8000}"
  "$CHROME" --headless=new --disable-gpu --no-sandbox \
    --window-size=1440,900 --virtual-time-budget="$budget" \
    --screenshot="$OUT/$name" "$BASE$path" >/dev/null
  echo "wrote $OUT/$name"
}

shot dashboard.png /
shot diagram.png /diagram 10000
shot logs.png /logs

echo "Screenshots ready under docs/images/ — commit and push to update the GitHub project page."