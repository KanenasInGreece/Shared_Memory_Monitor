#!/usr/bin/env bash
# Remove the shared-memory-monitor user unit. Leaves the checkout, .env and data/ in place.
# Never disables linger: it is per-user, and the gateway's own user unit on the same
# account depends on it, so turning it off would stop the gateway at the next logout.
set -euo pipefail

SERVICE_NAME="shared-memory-monitor.service"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$SERVICE_NAME"

systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$UNIT"
systemctl --user daemon-reload
systemctl --user reset-failed "$SERVICE_NAME" 2>/dev/null || true

if systemctl --user is-active --quiet "$SERVICE_NAME" \
    || [[ "$(systemctl --user show -p LoadState --value "$SERVICE_NAME")" != "not-found" ]]; then
  echo "✗ $SERVICE_NAME is still known to systemd — check: systemctl --user status $SERVICE_NAME" >&2
  exit 1
fi
echo "✓ $SERVICE_NAME removed (verified gone). Linger left unchanged."
echo "  data/ holds poll history and .env holds the token; remove the checkout only if the operator agrees."
