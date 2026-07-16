#!/usr/bin/env bash
# Upgrade monitor checkout to latest (or --ref TAG/BRANCH), reinstall deps, restart unit.
# Idempotent. Never prints secrets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--ref <tag-or-branch>]"
      echo "  Default: fast-forward current branch from origin (usually main)."
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if ! command -v git >/dev/null 2>&1; then
  echo "git required" >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv required — https://docs.astral.sh/uv/" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty — commit/stash before upgrade, or use a clean clone." >&2
  git status -sb
  exit 2
fi

echo "==> Pre-check (GitHub / origin)"
if [[ -x ./scripts/agent-status.sh ]]; then
  # Non-fatal: shows whether origin/main or a newer release tag is ahead
  ./scripts/agent-status.sh || true
  echo ""
fi

echo "==> Fetch origin"
git fetch origin --tags

if [[ -n "$REF" ]]; then
  echo "==> Checkout $REF"
  git checkout "$REF"
  # If ref is a branch that tracks origin, pull; tags are fixed
  if git show-ref --verify --quiet "refs/heads/$REF" 2>/dev/null; then
    git pull --ff-only origin "$REF" || true
  fi
else
  branch="$(git rev-parse --abbrev-ref HEAD)"
  echo "==> Fast-forward $branch"
  git pull --ff-only origin "$branch"
fi

echo "==> uv sync"
uv sync

if systemctl --user cat shared-memory-monitor.service >/dev/null 2>&1; then
  echo "==> Restart user unit"
  # Re-install unit if checkout path template needs refresh
  if [[ -x ./scripts/install-systemd-user.sh ]]; then
    # enable + restart without killing unrelated work more than needed
    ./scripts/install-systemd-user.sh
  else
    systemctl --user restart shared-memory-monitor.service
  fi
else
  echo "==> No user unit installed — start manually with:"
  echo "    ./scripts/run-loop.sh --serve --interval 600"
  echo "    or: ./scripts/install-systemd-user.sh"
fi

echo ""
echo "==> Post-upgrade status"
./scripts/agent-status.sh
exit $?
