#!/usr/bin/env bash
# Pre-push audit + git push to origin/main (for agents and maintainers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="${1:-main}"

./scripts/pre-publish-check.sh

if ! git remote get-url origin | grep -q 'github.com:KanenasInGreece/Shared_Memory_Monitor'; then
  echo "WARN: origin is not the expected SSH remote; fixing..." >&2
  git remote set-url origin git@github.com:KanenasInGreece/Shared_Memory_Monitor.git
fi

git push -u origin "HEAD:${BRANCH}"
echo "Published → https://github.com/KanenasInGreece/Shared_Memory_Monitor/tree/${BRANCH}"