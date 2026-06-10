#!/usr/bin/env bash
# Bootstrap monitor on a new machine — does not copy framework secrets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Installing Python dependencies"
uv sync

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
  echo "    Required: set AGENT_TOKEN (read-only monitor token) and COORDINATOR_URL"
  echo "    Optional:  SHARED_MEMORY_ROOT for REM audit log path discovery"
else
  echo "==> .env already exists (unchanged)"
fi

echo ""
echo "Prerequisites (gateway host):"
echo "  - hive-mind-gateway.service running (user unit)"
echo "  - monitor token in gateway AGENT_TOKENS with AGENT_ROLES=monitor:read"
echo "  - curl http://localhost:8888/health succeeds"
echo ""
echo "==> Environment check"
set +e
uv run python -m sm_telemetry_monitor check
code=$?
set -e

echo ""
if [[ $code -eq 0 ]]; then
  echo "Ready. Start with: ./scripts/run-loop.sh --serve --interval 600"
elif [[ $code -eq 2 ]]; then
  echo "Not ready — edit .env (AGENT_TOKEN + COORDINATOR_URL), confirm gateway is up, then:"
  echo "  ./scripts/check-env.sh"
else
  echo "Partial setup — see report above for optional panels (logs, etc.)."
fi
exit 0