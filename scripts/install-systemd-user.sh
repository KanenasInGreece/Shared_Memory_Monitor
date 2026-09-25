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

echo ""
echo "Ensuring user service survives logout (linger)..."
if loginctl enable-linger "$USER" 2>/dev/null; then
  echo "Linger enabled."
elif sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
  echo "Linger enabled (via sudo -n)."
else
  echo "WARNING: Could not enable linger."
  echo "  Without linger, the monitor will die when you log out."
  echo "  Please run this manually: sudo loginctl enable-linger $USER"
fi


# A listener on :8765 while our unit is NOT running is someone else's process (often a
# foreground run-loop). Stopping it is the operator's call, so refuse instead of killing it.
if ! systemctl --user is-active --quiet shared-memory-monitor.service \
    && command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ':8765 '; then
  echo "✗ Port 8765 is held by another process. Stop it (e.g. a foreground run-loop), then re-run." >&2
  exit 3
fi

systemctl --user restart shared-memory-monitor.service
# Wait for the dashboard so a status check straight after this does not report it down.
for _ in $(seq 1 30); do
  curl -sf -o /dev/null http://127.0.0.1:8765/api/meta && break
  sleep 0.5
done
systemctl --user --no-pager --lines=0 status shared-memory-monitor.service
echo ""
echo "Dashboard → http://127.0.0.1:8765/  (/diagram, /logs)"
echo "Status:    ./scripts/agent-status.sh"
echo "Doctor:    ./scripts/check-env.sh   # gateway version · API compat · telemetry panels · LLM placement"
