#!/usr/bin/env bash
# Install shared-memory-monitor as a systemd user service (survives logout with linger).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$ROOT/deploy/systemd/user/shared-memory-monitor.service"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/shared-memory-monitor.service"

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "Missing unit file: $UNIT_SRC" >&2
  exit 1
fi

mkdir -p "$(dirname "$UNIT_DST")"
sed "s|@MONITOR_ROOT@|$ROOT|g" "$UNIT_SRC" > "$UNIT_DST"
echo "Installed → $UNIT_DST (MONITOR_ROOT=$ROOT)"

systemctl --user daemon-reload
systemctl --user enable shared-memory-monitor.service

if ss -tln 2>/dev/null | grep -q ':8765 '; then
  echo ""
  echo "Port 8765 in use — stopping foreground listener, then starting user unit..."
  fuser -k 8765/tcp 2>/dev/null || true
  sleep 0.5
fi

systemctl --user restart shared-memory-monitor.service
systemctl --user --no-pager status shared-memory-monitor.service
echo ""
echo "Dashboard → http://127.0.0.1:8765/"