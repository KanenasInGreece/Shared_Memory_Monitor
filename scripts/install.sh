#!/usr/bin/env bash
# Bootstrap monitor on a new machine — does not copy framework secrets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PKG_VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"

echo "==> Installing Python dependencies (sm-telemetry-monitor ${PKG_VERSION:-?})"
uv sync

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
  echo "    Required: set AGENT_TOKEN (read-only monitor token) and COORDINATOR_URL"
  echo "    Optional:  SHARED_MEMORY_ROOT / BACKUP_DIR for logs + sidebar backup date"
else
  echo "==> .env already exists (unchanged)"
fi

echo ""
echo "Prerequisites (gateway host — this monitor is a view only):"
echo "  - hive-mind-gateway.service running (user unit)"
echo "  - monitor token in gateway AGENT_TOKENS with AGENT_ROLES=monitor:read"
echo "  - curl \$COORDINATOR_URL/health succeeds (default http://localhost:8888)"
echo "  - Wire contract: monitor API v3 ↔ framework api_version 3 (gateway ≥0.7.0)"
echo "  - Full UI (LLM local/external badges, graph/latency drawers): gateway ≥0.8.9"
echo ""
echo "Before git push, run: ./scripts/pre-publish-check.sh"
echo ""
echo "==> Environment check"
set +e
uv run python -m sm_telemetry_monitor check
code=$?
set -e

echo ""
echo "What the doctor lines mean for the dashboard:"
echo "  coordinator … placement local|external  → Infrastructure config + LLM pool chips"
echo "  telemetry … nrem+breakdown+consolidation+entity_graph+latency+spine+compliance"
echo "    → backlog/NREM, schema drawer, consolidation drawer, latency drawer"
echo "  Missing panel names = older gateway; UI omits those bands (no crash)."
echo ""
if [[ $code -eq 0 ]]; then
  echo "Ready."
  echo "  Foreground:  ./scripts/run-loop.sh --serve --interval 600"
  echo "  Persistent:  ./scripts/install-systemd-user.sh"
  echo "  Status:      ./scripts/agent-status.sh"
  echo "  Dashboard:   http://127.0.0.1:8765/  (/diagram, /logs)"
elif [[ $code -eq 2 ]]; then
  echo "Not ready — edit .env (AGENT_TOKEN + COORDINATOR_URL), confirm gateway is up, then:"
  echo "  ./scripts/check-env.sh"
  echo "  ./scripts/agent-status.sh"
else
  echo "Partial setup — see report above (logs optional if remote HTTP-only)."
  echo "  Re-check: ./scripts/check-env.sh"
  echo "  When green enough: ./scripts/run-loop.sh --serve --interval 600"
fi
exit 0
