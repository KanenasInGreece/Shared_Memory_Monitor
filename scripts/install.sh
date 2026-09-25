#!/usr/bin/env bash
# Bootstrap monitor on a new machine — does not copy framework secrets.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PKG_VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv required — https://docs.astral.sh/uv/" >&2
  exit 2
fi

echo "==> Installing Python dependencies (sm-telemetry-monitor ${PKG_VERSION:-?})"
uv sync

if [[ ! -f .env ]]; then
  (umask 077 && cp .env.example .env)   # owner-only before a token is ever pasted in
  echo "==> Created .env from .env.example"
  echo "    Required: set AGENT_TOKEN (read-only monitor token) and COORDINATOR_URL"
  echo "    Optional:  SHARED_MEMORY_ROOT / BACKUP_DIR for logs + sidebar backup date"
  echo ""
  echo "    Next: the operator pastes the monitor token into .env (OPERATE.md Install step 3), then ./scripts/check-env.sh"
  exit 0
else
  echo "==> .env already exists (unchanged)"
fi

echo "==> Environment check"
set +e
uv run python -m sm_telemetry_monitor check
code=$?
set -e

echo ""
if [[ $code -eq 0 ]]; then
  echo "Ready."
  echo "  Foreground:  ./scripts/run-loop.sh --serve --interval 600"
  echo "  Persistent:  ./scripts/install-systemd-user.sh"
  echo "  Status:      ./scripts/agent-status.sh"
  echo "  Dashboard:   http://127.0.0.1:8765/  (/diagram, /logs)"
elif [[ $code -eq 2 ]]; then
  echo "Not ready — token missing or rejected, or gateway down (OPERATE.md Install step 3). Then:"
  echo "  ./scripts/check-env.sh"
  echo "  ./scripts/agent-status.sh"
else
  echo "Partial setup — see report above (logs optional if remote HTTP-only)."
  echo "  Re-check: ./scripts/check-env.sh"
  echo "  When green enough: ./scripts/run-loop.sh --serve --interval 600"
fi
exit 0
